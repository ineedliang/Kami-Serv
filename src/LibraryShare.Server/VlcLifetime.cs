using System.Diagnostics;

namespace LibraryShare;

// Watch actual process handles, not a Lua panel-close callback or a process name
// search. That also covers crashes and avoids confusing reused process IDs.
public sealed class VlcLifetime(ServerOptions options, IHostApplicationLifetime host) : BackgroundService
{
    private readonly object gate = new();
    private readonly Dictionary<(int Pid, long Created), Process> owners = new();
    private bool bound;
    public int OwnerCount { get { lock (gate) return owners.Count; } }

    public void Attach(int pid, long created)
    {
        if (pid <= 0 || created <= 0) throw new ArgumentException("A running VLC process and its creation time are required.");
        Process? process = null;
        try
        {
            process = Process.GetProcessById(pid);
            // Open the handle now so a later PID reuse cannot change the owner.
            _ = process.Handle;
            var expectedDirectory = Environment.GetEnvironmentVariable("VLC_DIR");
            if (process.HasExited || process.StartTime.ToUniversalTime().Ticks != created ||
                !process.ProcessName.Equals("vlc", StringComparison.OrdinalIgnoreCase) ||
                process.SessionId != Process.GetCurrentProcess().SessionId ||
                (expectedDirectory is not null && !string.Equals(process.MainModule?.FileName,
                    Path.Combine(expectedDirectory, "vlc.exe"), StringComparison.OrdinalIgnoreCase)))
                throw new ArgumentException("The VLC owner is no longer running or does not match this installation.");
            lock (gate)
            {
                if (host.ApplicationStopping.IsCancellationRequested) throw new ArgumentException("The helper is stopping; reopen the panel to restart it.");
                if (!owners.TryAdd((pid, created), process)) process.Dispose();
                process = null;
                bound = true;
            }
        }
        catch (Exception e) when (e is InvalidOperationException or System.ComponentModel.Win32Exception)
        { throw new ArgumentException("Could not attach to the running VLC process. Reopen VLC and try again.", e); }
        finally { process?.Dispose(); }
    }

    public override Task StartAsync(CancellationToken cancellationToken)
    {
        if (options.OwnerPid > 0) Attach(options.OwnerPid, options.OwnerStarted);
        return base.StartAsync(cancellationToken);
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        try
        {
            while (!stoppingToken.IsCancellationRequested)
            {
                lock (gate)
                {
                    foreach (var pair in owners.Where(p => p.Value.HasExited).ToArray())
                    { owners.Remove(pair.Key); pair.Value.Dispose(); }
                    if (bound && owners.Count == 0)
                    {
                        Console.WriteLine("VLC closed; stopping Library Share and its workers.");
                        host.StopApplication();
                        return;
                    }
                }
                await Task.Delay(250, stoppingToken);
            }
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { }
        finally
        {
            lock (gate) { foreach (var process in owners.Values) process.Dispose(); owners.Clear(); }
        }
    }
}
