using System.Diagnostics;
using System.Text.Json;

namespace LibraryShare;

// Only an explicit Allow action requests elevation. Status never changes the firewall.
public sealed class FirewallSetup(ServerOptions options, CancellationToken shutdown)
{
    private readonly object gate = new();
    private bool busy;
    private string message = "Windows Firewall: use Check or Allow / repair on the Server & playback page.";
    private string state = "unchecked";
    public bool Active { get { lock (gate) return busy; } }
    public string Message { get { lock (gate) return message; } }
    public string State { get { lock (gate) return state; } }

    public void Start(bool allow)
    {
        lock (gate)
        {
            if (busy) throw new ArgumentException("Firewall setup/check is already running. Finish the Windows permission prompt first.");
            busy = true;
            state = "working";
            message = allow ? "Waiting for Windows administrator permission to allow sharing on Private networks..." : "Checking Windows Firewall...";
        }
        _ = Task.Run(async () =>
        {
            try
            {
                var start = new ProcessStartInfo("powershell.exe") { UseShellExecute = false, CreateNoWindow = true,
                    RedirectStandardOutput = true, RedirectStandardError = true };
                foreach (var argument in new[] { "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    Path.Combine(options.ProjectDirectory, "scripts", "configure-firewall.ps1"), "-Action", allow ? "Allow" : "Status",
                    "-ProgramPath", Environment.ProcessPath!, "-Port", options.Port.ToString(System.Globalization.CultureInfo.InvariantCulture) })
                    start.ArgumentList.Add(argument);
                using var process = Process.Start(start) ?? throw new IOException("Could not launch Windows Firewall setup.");
                using var cancellation = shutdown.Register(() => { try { if (!process.HasExited) process.Kill(true); } catch (InvalidOperationException) { } catch (System.ComponentModel.Win32Exception) { } });
                var output = process.StandardOutput.ReadToEndAsync(shutdown);
                var error = process.StandardError.ReadToEndAsync(shutdown);
                await process.WaitForExitAsync(shutdown);
                var result = await output;
                await error; // Drain stderr; output is structured and never displayed as raw process text.
                using var document = JsonDocument.Parse(result);
                var root = document.RootElement;
                var reportedState = root.GetProperty("State").GetString() ?? "failed";
                var reportedMessage = root.GetProperty("Message").GetString() ?? "No firewall result returned.";
                if (reportedState is not ("configured" or "not-configured" or "cancelled" or "failed")) throw new IOException("Unexpected firewall result.");
                if (process.ExitCode != 0 && reportedState != "failed") throw new IOException("Firewall setup did not finish successfully.");
                lock (gate) { state = reportedState; message = reportedMessage; }
            }
            catch (Exception e) when (e is IOException or JsonException or InvalidOperationException or KeyNotFoundException or
                System.ComponentModel.Win32Exception or OperationCanceledException)
            { lock (gate) { state = "failed"; message = "Firewall setup/check failed: " + e.Message; } }
            finally { lock (gate) busy = false; }
        }, CancellationToken.None);
    }
}
