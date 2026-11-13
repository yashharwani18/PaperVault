using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Reflection;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: AssemblyVersion("0.5.0.0")]
[assembly: AssemblyFileVersion("0.5.0.0")]
[assembly: AssemblyProduct("PaperVault")]
[assembly: AssemblyTitle("PaperVault")]
[assembly: AssemblyDescription("PaperVault v0.5 — Whole-PC Neural Document Studio")]

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        string root = AppDomain.CurrentDomain.BaseDirectory;
        bool release = File.Exists(Path.Combine(root, "release.json"));
        string library = release ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "LocalKnowledgeLibrary", "library") : Path.Combine(root, "data", "library");
        string localConfig = Path.Combine(root, "PaperVault.user.json");
        if (!File.Exists(localConfig)) localConfig = Path.Combine(root, "Library.user.json");
        if (File.Exists(localConfig))
        {
            try { library = new JavaScriptSerializer().Deserialize<Config>(File.ReadAllText(localConfig)).library_path ?? library; }
            catch { /* A malformed local preference must not prevent startup. */ }
        }
        int debugPort = 0;
        bool quit = false, waitForExit = false, startMinimized = false;
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "--library" && i + 1 < args.Length) library = args[++i];
            else if (args[i] == "--debug-port" && i + 1 < args.Length) { int port = int.Parse(args[++i]); if (!release) debugPort = port; }
            else if (args[i] == "--quit") quit = true;
            else if (args[i] == "--wait") waitForExit = true;
            else if (args[i] == "--minimized" || args[i] == "--startup") startMinimized = true;
        }
        library = Path.GetFullPath(library);
        string key;
        using (var sha = SHA256.Create())
            key = BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(library.ToLowerInvariant()))).Replace("-", "").Substring(0, 24);
        bool first;
        using (var mutex = new Mutex(true, "Local\\LocalLibrary." + key, out first))
        using (var show = new EventWaitHandle(false, EventResetMode.AutoReset, "Local\\LocalLibrary.Show." + key))
        using (var exit = new EventWaitHandle(false, EventResetMode.AutoReset, "Local\\LocalLibrary.Exit." + key))
        {
            if (quit)
            {
                if (!first)
                {
                    exit.Set();
                    if (waitForExit)
                    {
                        try { if (mutex.WaitOne(30000)) mutex.ReleaseMutex(); else Environment.ExitCode = 1; }
                        catch (AbandonedMutexException) { mutex.ReleaseMutex(); }
                    }
                }
                return;
            }
            if (!first) { show.Set(); return; }
            try { Application.Run(new LibraryWindow(root, library, show, exit, debugPort, startMinimized)); }
            catch (Exception error) { MessageBox.Show(error.Message, "PaperVault could not start", MessageBoxButtons.OK, MessageBoxIcon.Error); }
        }
    }
    public class Config { public Config() {} public string library_path { get; set; } }
}

public sealed class BackendReady
{
    public string url { get; set; }
    public string token { get; set; }
    public int pid { get; set; }
}

internal sealed class LibraryWindow : Form
{
    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);
    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        try { int dark = 1; DwmSetWindowAttribute(Handle, 20, ref dark, sizeof(int)); } catch { }
    }
    private readonly string root, library, readyPath;
    private readonly EventWaitHandle showSignal;
    private readonly EventWaitHandle exitSignal;
    private readonly int debugPort;
    private readonly WebView2 view = new WebView2();
    private readonly Label status = new Label();
    private readonly Label help = new Label();
    private readonly NotifyIcon tray = new NotifyIcon();
    private readonly System.Windows.Forms.Timer signalTimer = new System.Windows.Forms.Timer();
    private readonly HttpClient http = new HttpClient(new HttpClientHandler { UseProxy = false });
    private Process backend;
    private BackendReady ready;
    private bool stopping, closed, everReady, startMinimized;

    internal LibraryWindow(string root, string library, EventWaitHandle showSignal, EventWaitHandle exitSignal, int debugPort, bool startMinimized = false)
    {
        this.root = root; this.library = library; this.showSignal = showSignal; this.debugPort = debugPort;
        this.exitSignal = exitSignal;
        this.startMinimized = startMinimized;
        Text = "PaperVault v0.5";
        StartPosition = FormStartPosition.CenterScreen;
        Size = new Size(1320, 920);
        MinimumSize = new Size(960, 650);
        BackColor = Color.FromArgb(27, 24, 29);
        ForeColor = Color.FromArgb(235, 231, 238);
        Icon = Icon.ExtractAssociatedIcon(Path.Combine(root, "Library.exe"));
        status.Dock = DockStyle.Fill;
        status.TextAlign = ContentAlignment.MiddleCenter;
        status.Font = new Font("Segoe UI", 18);
        status.Text = "Opening PaperVault…\nStarting the whole-PC document engine.";
        help.Dock = DockStyle.Bottom;
        help.Height = 28;
        help.TextAlign = ContentAlignment.MiddleLeft;
        help.Padding = new Padding(12, 0, 0, 0);
        help.Font = new Font("Segoe UI", 9);
        help.ForeColor = Color.FromArgb(176, 166, 182);
        help.Text = "Minimize to keep whole-PC indexing running in the tray. Closing this window exits PaperVault.";
        view.Dock = DockStyle.Fill;
        view.DefaultBackgroundColor = BackColor;
        view.Visible = false;
        Controls.Add(status); Controls.Add(view); Controls.Add(help);
        tray.Icon = Icon;
        tray.Text = "PaperVault v0.5 — Whole-PC Neural Document Studio";
        var menu = new ContextMenuStrip { BackColor = BackColor, ForeColor = ForeColor };
        menu.Items.Add("Open PaperVault", null, (s, e) => RestoreWindow());
        menu.Items.Add("Exit PaperVault", null, (s, e) => Close());
        tray.ContextMenuStrip = menu;
        tray.DoubleClick += (s, e) => RestoreWindow();
        tray.Visible = true;
        if (startMinimized)
        {
            WindowState = FormWindowState.Minimized;
            ShowInTaskbar = false;
        }
        signalTimer.Interval = 300;
        signalTimer.Tick += (s, e) => { if (exitSignal.WaitOne(0)) Close(); else if (showSignal.WaitOne(0)) RestoreWindow(); };
        signalTimer.Start();
        Resize += (s, e) => { if (WindowState == FormWindowState.Minimized && everReady) Hide(); };
        Shown += async (s, e) => {
            if (startMinimized) Hide();
            await StartEngine();
        };
        FormClosing += OnClosing;
        FormClosed += (s, e) => { closed = true; signalTimer.Stop(); tray.Visible = false; tray.Dispose(); http.Dispose(); };
        readyPath = Path.Combine(library, "native", "session-" + Guid.NewGuid().ToString("N") + ".json");
    }

    private void RestoreWindow()
    {
        Show(); WindowState = FormWindowState.Normal; Activate();
    }

    private static string Quote(string value) { return "\"" + value.Replace("\"", "") + "\""; }

    private async Task StartEngine()
    {
        bool failed = false;
        try
        {
            string python = Path.Combine(root, "runtime", "pythonw.exe");
            string app = Path.Combine(root, "app");
            if (!File.Exists(python) || !File.Exists(Path.Combine(app, "frontend", "dist", "index.html")))
                throw new InvalidOperationException("The application folder is incomplete. Keep Library.exe together with its runtime and app folders.");
            Directory.CreateDirectory(Path.GetDirectoryName(readyPath));
            string launcher = File.Exists(Path.Combine(app, "launch.py")) ? Quote(Path.Combine(app, "launch.py")) : "-m knowledge_library.desktop_runtime";
            var start = new ProcessStartInfo(python, "-B -u " + launcher + " --library " + Quote(library)
                + " --ready-file " + Quote(readyPath) + " --parent-pid " + Process.GetCurrentProcess().Id);
            start.WorkingDirectory = app;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            start.EnvironmentVariables.Remove("PYTHONPATH");
            start.EnvironmentVariables.Remove("PYTHONHOME");
            backend = Process.Start(start);
            var deadline = DateTime.UtcNow.AddSeconds(100);
            while (DateTime.UtcNow < deadline)
            {
                if (stopping || closed) return;
                if (backend.HasExited)
                    throw new InvalidOperationException("The document engine stopped. Check " + Path.Combine(library, "native", "backend.log"));
                if (File.Exists(readyPath))
                {
                    ready = new JavaScriptSerializer().Deserialize<BackendReady>(File.ReadAllText(readyPath));
                    if (ready.pid != backend.Id) throw new InvalidOperationException("The engine identity did not match this window.");
                    break;
                }
                await Task.Delay(150);
            }
            if (ready == null) throw new TimeoutException("Starting the document engine took too long. Check the local backend log and reopen Khoj.");
            status.Text = "Opening your workspace…";
            var options = new CoreWebView2EnvironmentOptions();
            if (debugPort > 0) options.AdditionalBrowserArguments = "--remote-debugging-port=" + debugPort;
            var environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(library, "native", "webview2"), options);
            if (stopping || closed) return;
            await view.EnsureCoreWebView2Async(environment);
            view.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
            view.CoreWebView2.Settings.AreDevToolsEnabled = debugPort > 0;
            view.CoreWebView2.Settings.IsStatusBarEnabled = false;
            view.CoreWebView2.Settings.AreHostObjectsAllowed = false;
            view.CoreWebView2.Settings.IsWebMessageEnabled = false;
            view.CoreWebView2.AddWebResourceRequestedFilter(ready.url + "/api/connections/pick", CoreWebView2WebResourceContext.All);
            view.CoreWebView2.WebResourceRequested += (s, e) =>
            {
                string token = e.Request.Headers.Contains("X-Library-Token") ? e.Request.Headers.GetHeader("X-Library-Token") : "";
                if (e.Request.Method != "POST" || token != ready.token)
                {
                    e.Response = environment.CreateWebResourceResponse(new MemoryStream(Encoding.UTF8.GetBytes("{\"detail\":\"Reload Khoj before choosing a folder.\"}")), 403, "Forbidden", "Content-Type: application/json");
                    return;
                }
                using (var picker = new FolderBrowserDialog())
                {
                    picker.Description = "Choose a folder to connect to Khoj";
                    picker.ShowNewFolderButton = false;
                    picker.SelectedPath = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
                    string path = picker.ShowDialog(this) == DialogResult.OK ? picker.SelectedPath : null;
                    string json = new JavaScriptSerializer().Serialize(new { path = path });
                    e.Response = environment.CreateWebResourceResponse(new MemoryStream(Encoding.UTF8.GetBytes(json)), 200, "OK", "Content-Type: application/json; charset=utf-8");
                }
            };
            view.CoreWebView2.NavigationStarting += (s, e) =>
            {
                if (!IsLocal(e.Uri)) e.Cancel = true;
            };
            view.CoreWebView2.NewWindowRequested += (s, e) =>
            {
                e.Handled = true;
                if (IsLocal(e.Uri)) OpenSourceWindow(e.Uri, environment);
                else if (e.IsUserInitiated && e.Uri.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
                    Process.Start(new ProcessStartInfo(e.Uri) { UseShellExecute = true });
            };
            view.NavigationCompleted += (s, e) =>
            {
                if (e.IsSuccess) { view.Visible = true; status.Visible = false; everReady = true; }
                else status.Text = "The workspace could not load. Close and reopen Khoj.\n" + e.WebErrorStatus;
            };
            backend.EnableRaisingEvents = true;
            backend.Exited += (s, e) =>
            {
                if (!stopping && !closed && IsHandleCreated)
                    BeginInvoke((Action)(() => { view.Visible = false; status.Visible = true; status.Text = "The document engine stopped.\nClose and reopen Khoj to restart it. Your saved documents are retained."; }));
            };
            view.Source = new Uri(ready.url);
        }
        catch (Exception error)
        {
            if (!closed) status.Text = "Khoj could not start\n\n" + error.Message;
            failed = true;
        }
        if (failed) await StopEngine();
    }

    private bool IsLocal(string uri)
    {
        Uri value, origin;
        return ready != null && Uri.TryCreate(uri, UriKind.Absolute, out value) && Uri.TryCreate(ready.url, UriKind.Absolute, out origin)
            && value.Scheme == origin.Scheme && value.Host == origin.Host && value.Port == origin.Port;
    }

    private async void OpenSourceWindow(string uri, CoreWebView2Environment environment)
    {
        var source = new Form { Text = "Khoj — source document", Size = new Size(1000, 850), Icon = Icon };
        var document = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = BackColor };
        source.Controls.Add(document);
        source.Show(this);
        try
        {
            await document.EnsureCoreWebView2Async(environment);
            document.CoreWebView2.Settings.AreDevToolsEnabled = false;
            document.CoreWebView2.NavigationStarting += (s, e) => { if (!IsLocal(e.Uri)) e.Cancel = true; };
            document.Source = new Uri(uri);
        }
        catch { source.Close(); }
    }

    private async void OnClosing(object sender, FormClosingEventArgs e)
    {
        if (stopping) return;
        e.Cancel = true;
        stopping = true;
        Hide();
        await StopEngine();
        Close();
    }

    private async Task StopEngine()
    {
        if (backend == null) return;
        try
        {
            if (!backend.HasExited && ready != null)
            {
                var request = new HttpRequestMessage(HttpMethod.Post, ready.url + "/api/desktop/shutdown");
                request.Headers.Add("X-Library-Token", ready.token);
                http.Timeout = TimeSpan.FromSeconds(3);
                await http.SendAsync(request);
            }
        }
        catch { }
        for (int i = 0; i < 100 && !backend.HasExited; i++) await Task.Delay(100);
        if (!backend.HasExited) backend.Kill();
        backend.Dispose(); backend = null;
        try { File.Delete(readyPath); } catch { }
    }
}
