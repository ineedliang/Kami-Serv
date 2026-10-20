using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

// Small, per-user setup bootstrapper built with the C# compiler supplied by Windows.
// The media helper uses .NET 8; setup itself uses Windows' .NET Framework.
internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        string temporary = null;
        try
        {
            if (args.Length == 2 && args[0] == "--extract-only")
            {
                Extract(Path.GetFullPath(args[1]));
                return 0;
            }
            if (args.Length != 0) return 2;
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            temporary = Path.Combine(Path.GetTempPath(), "LibraryShare-Setup-" + Guid.NewGuid().ToString("N"));
            Extract(temporary);
            Application.Run(new SetupForm(temporary));
            return 0;
        }
        catch (Exception error)
        {
            if (args.Length == 0) MessageBox.Show(error.Message, "Library Share setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        finally
        {
            // Only this run's generated temporary directory can be cleaned up.
            if (temporary != null && Path.GetDirectoryName(temporary).Equals(Path.GetTempPath().TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase)
                && Path.GetFileName(temporary).StartsWith("LibraryShare-Setup-", StringComparison.Ordinal))
            {
                try { Directory.Delete(temporary, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
            }
        }
    }

    private static void Extract(string destination)
    {
        if (Directory.Exists(destination) && Directory.GetFileSystemEntries(destination).Length != 0)
            throw new IOException("The extraction folder must be empty.");
        Directory.CreateDirectory(destination);
        string prefix = destination.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        using (Stream resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("LibraryShare.Payload.zip"))
        using (var archive = new ZipArchive(resource, ZipArchiveMode.Read))
        {
            foreach (ZipArchiveEntry entry in archive.Entries)
            {
                string target = Path.GetFullPath(Path.Combine(destination, entry.FullName));
                if (!target.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new IOException("Invalid installer payload path.");
                if (entry.Name.Length == 0) { Directory.CreateDirectory(target); continue; }
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                entry.ExtractToFile(target, false);
            }
        }
        foreach (string required in new[] { "server/LibraryShare.Server.exe", "vlc/library_share.lua", "scripts/install-vlc-plugin.ps1", "scripts/uninstall.ps1" })
            if (!File.Exists(Path.Combine(destination, required))) throw new IOException("Installer payload is incomplete.");
    }
}

internal sealed class Result
{
    internal int Code;
    internal string Output;
    internal string Error;
}

internal sealed class SetupForm : Form
{
    private readonly string payload;
    private readonly string destination = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "LibraryShare");
    private readonly TextBox vlc = new TextBox();
    private readonly TextBox status = new TextBox();
    private readonly CheckBox firewall = new CheckBox();
    private readonly CheckBox desktop = new CheckBox();
    private readonly Button install = new Button();
    private readonly Button check = new Button();
    private readonly Button close = new Button();
    private readonly Button browse = new Button();
    private bool busy;
    private bool installed;

    internal SetupForm(string payloadDirectory)
    {
        payload = payloadDirectory;
        Text = "Library Share for VLC - Setup";
        Font = new Font("Segoe UI", 9F);
        ClientSize = new Size(650, 540);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.Dpi;
        AddLabel("Library Share for VLC", 22, 18, 600, 34, new Font(Font.FontFamily, 20F, FontStyle.Bold));
        AddLabel("Alpha 0.3.0 (SRT update) - Share selected media folders with your TVs, phones and tablets.", 24, 62, 600, 26, null);
        AddLabel("Requires 64-bit Windows 10/11, desktop VLC 3.x (64-bit),\r\nand the .NET 8 ASP.NET Core Runtime (x64).", 24, 92, 605, 43, null);
        AddLink("Get VLC", "https://www.videolan.org/vlc/", 24, 140, 115);
        AddLink("Get .NET 8 runtime", "https://dotnet.microsoft.com/en-us/download/dotnet/8.0", 150, 140, 165);
        AddLabel("VLC installation folder", 24, 178, 600, 23, null);
        vlc.SetBounds(24, 204, 493, 27);
        vlc.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "VideoLAN", "VLC");
        Controls.Add(vlc);
        browse.Text = "Browse..."; browse.SetBounds(529, 202, 95, 29);
        browse.Click += delegate {
            using (var picker = new FolderBrowserDialog())
            {
                picker.Description = "Select the desktop VLC 3.x installation folder";
                picker.ShowNewFolderButton = false;
                if (Directory.Exists(vlc.Text)) picker.SelectedPath = vlc.Text;
                if (picker.ShowDialog(this) == DialogResult.OK) vlc.Text = picker.SelectedPath;
            }
        };
        Controls.Add(browse);
        AddLabel("Install for your Windows account:\r\n" + destination, 24, 246, 600, 43, null);
        firewall.Text = "Allow sharing on Private networks (requests administrator permission)";
        firewall.Checked = true; firewall.SetBounds(24, 300, 605, 25); Controls.Add(firewall);
        desktop.Text = "Create a desktop shortcut"; desktop.SetBounds(24, 329, 605, 25); Controls.Add(desktop);
        status.SetBounds(24, 366, 600, 100); status.Multiline = true; status.ReadOnly = true;
        status.ScrollBars = ScrollBars.Vertical;
        status.Text = "New installs start with sharing off and no selected folders.\r\nUpgrades keep your library settings and prepared videos.\r\nThis independent project is not an official VideoLAN product.";
        Controls.Add(status);
        check.Text = "Check requirements"; check.SetBounds(24, 489, 160, 32);
        check.Click += async delegate { await CheckRequirements(); }; Controls.Add(check);
        install.Text = "Install"; install.SetBounds(394, 489, 110, 32);
        install.Click += async delegate { if (installed) { Launch(); Close(); } else await Install(); }; Controls.Add(install);
        close.Text = "Cancel"; close.SetBounds(514, 489, 110, 32); close.Click += delegate { Close(); }; Controls.Add(close);
        AcceptButton = install; CancelButton = close;
        FormClosing += delegate(object sender, FormClosingEventArgs e) { if (busy) e.Cancel = true; };
    }

    private void AddLabel(string text, int x, int y, int width, int height, Font font)
    {
        var label = new Label { Text = text, AutoSize = false };
        if (font != null) label.Font = font;
        label.SetBounds(x, y, width, height); Controls.Add(label);
    }
    private void AddLink(string text, string url, int x, int y, int width)
    {
        var link = new LinkLabel { Text = text, AutoSize = false };
        link.SetBounds(x, y, width, 25);
        link.LinkClicked += delegate { try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); } catch (Exception error) { status.Text = error.Message; } };
        Controls.Add(link);
    }
    private void SetBusy(bool value)
    {
        busy = value;
        install.Enabled = check.Enabled = close.Enabled = browse.Enabled = vlc.Enabled = firewall.Enabled = desktop.Enabled = !value;
        UseWaitCursor = value;
    }
    private async Task<bool> CheckRequirements()
    {
        SetBusy(true); status.Text = "Checking VLC and required runtimes...";
        try
        {
            string folder = vlc.Text;
            Result result = await Task.Run(() => Run("check-prerequisites.ps1", "-VlcDirectory", folder, "-Json"));
            var report = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(result.Output);
            status.Text = Convert.ToString(report["Message"]);
            return result.Code == 0 && Convert.ToBoolean(report["Ready"]);
        }
        catch (Exception error) { status.Text = "Could not check requirements: " + error.Message; return false; }
        finally { SetBusy(false); }
    }
    private async Task Install()
    {
        if (!await CheckRequirements()) return;
        SetBusy(true); status.Text = "Installing Library Share...\r\nApprove the Windows permission prompt if you selected firewall access.";
        try
        {
            var arguments = new List<string> { "-VlcDirectory", vlc.Text, "-Destination", destination, "-NoLaunch", "-RegisterApplication" };
            if (firewall.Checked) arguments.Add("-ConfigureFirewall");
            if (desktop.Checked) arguments.Add("-DesktopShortcut");
            Result result = await Task.Run(() => Run("install-vlc-plugin.ps1", arguments.ToArray()));
            if (result.Code != 0) throw new IOException(result.Error.Length > 0 ? result.Error : result.Output);
            status.Text = "Installed. Open VLC, then choose View > Share Library.\r\nChoose folders, then Enable sharing. Closing VLC stops sharing.\r\n\r\n" + result.Output;
            installed = true; install.Text = "Open VLC"; close.Text = "Finish";
        }
        catch (Exception error) { status.Text = "Installation could not finish:\r\n" + error.Message; }
        finally { SetBusy(false); check.Enabled = !installed; }
    }
    private Result Run(string script, params string[] arguments)
    {
        var args = new List<string> { "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", Path.Combine(payload, "scripts", script) };
        args.AddRange(arguments);
        var command = new StringBuilder();
        foreach (string argument in args) { if (command.Length > 0) command.Append(' '); command.Append(Quote(argument)); }
        var start = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "WindowsPowerShell", "v1.0", "powershell.exe"), command.ToString())
        { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
          StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8, WorkingDirectory = payload };
        using (var process = Process.Start(start))
        {
            Task<string> output = process.StandardOutput.ReadToEndAsync();
            Task<string> error = process.StandardError.ReadToEndAsync();
            process.WaitForExit();
            return new Result { Code = process.ExitCode, Output = output.Result, Error = error.Result };
        }
    }
    private void Launch()
    {
        Process.Start(new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "WindowsPowerShell", "v1.0", "powershell.exe"),
            "-NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File " + Quote(Path.Combine(destination, "scripts", "launch-share.ps1")))
            { UseShellExecute = false, CreateNoWindow = true });
    }
    private static string Quote(string text)
    {
        var quoted = new StringBuilder("\"");
        int backslashes = 0;
        foreach (char c in text)
        {
            if (c == '\\') { backslashes++; continue; }
            if (c == '"') quoted.Append('\\', backslashes * 2 + 1);
            else quoted.Append('\\', backslashes);
            quoted.Append(c); backslashes = 0;
        }
        quoted.Append('\\', backslashes * 2); quoted.Append('"');
        return quoted.ToString();
    }
}
