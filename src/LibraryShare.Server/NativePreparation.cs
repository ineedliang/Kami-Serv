using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

namespace LibraryShare;

public sealed record PreparationJob(string Input, string Output, string VlcDirectory, PlaybackSettings Settings,
    bool BurnSubtitles, int SubtitleTrack, double? Seconds, int TimeoutSeconds = 86400);

// Runs in a separate copy of this executable. Native codec failures or cancellation
// cannot take down the server; closing VLC cancels and kills this worker process.
public static class NativePreparation
{
    private const string Vlc = "libvlc.dll";

    [StructLayout(LayoutKind.Sequential)]
    private struct NativeTrack
    {
        public uint Codec, OriginalCodec;
        public int Id, Type, Profile, Level;
        public IntPtr Details;
        public uint Bitrate;
        public IntPtr Language, Description;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct NativeAudio { public uint Channels, Rate; }
    private sealed record Track(int Type, int Index, int Id, string Codec, string Language, string Description, uint? Channels, uint? Rate);

    public static async Task<int> Run(string jobPath)
    {
        try
        {
            var job = JsonSerializer.Deserialize<PreparationJob>(await File.ReadAllTextAsync(jobPath)) ?? throw new InvalidDataException("Invalid preparation job.");
            job.Settings.Validate();
            var input = Path.GetFullPath(job.Input);
            var output = Path.GetFullPath(job.Output);
            if (input.Equals(output, StringComparison.OrdinalIgnoreCase)) throw new IOException("Output must not replace the input file.");
            if (!File.Exists(input)) throw new FileNotFoundException("Source file is missing.");
            if (File.Exists(output)) throw new IOException("Output already exists; it will not be overwritten.");
            if (job.SubtitleTrack is < 0 or > 99 || job.TimeoutSeconds is < 1 or > 86400 ||
                job.Seconds is <= 0 || job.Seconds is { } seconds && !double.IsFinite(seconds)) throw new ArgumentException("Invalid preparation limits.");
            Directory.CreateDirectory(Path.GetDirectoryName(output)!);
            var directory = Path.GetFullPath(job.VlcDirectory);
            if (!Directory.Exists(Path.Combine(directory, "plugins"))) throw new IOException("VLC plugins are missing. Select the desktop VLC installation.");
            if (!SetDefaultDllDirectories(0x1000)) throw new IOException("Could not configure the native library search path.");
            var cookie = AddDllDirectory(directory);
            if (cookie == IntPtr.Zero) throw new IOException("Could not load the VLC installation directory.");
            IntPtr handle = IntPtr.Zero;
            try
            {
                handle = NativeLibrary.Load(Path.Combine(directory, Vlc));
                NativeLibrary.SetDllImportResolver(typeof(NativePreparation).Assembly, (name, _, _) => name == Vlc ? handle : IntPtr.Zero);
                // Ignore any VLC_PLUGIN_PATH belonging to a portable preview or a different VLC install.
                Environment.SetEnvironmentVariable("VLC_PLUGIN_PATH", Path.Combine(directory, "plugins"));
                Environment.SetEnvironmentVariable("VLC_DATA_PATH", directory);
                await Prepare(job with { Input = input, Output = output });
            }
            finally
            {
                if (handle != IntPtr.Zero) NativeLibrary.Free(handle);
                RemoveDllDirectory(cookie);
            }
            return 0;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or ArgumentException or JsonException or
            DllNotFoundException or BadImageFormatException or EntryPointNotFoundException or InvalidOperationException or TimeoutException)
        {
            Console.Error.WriteLine(error.Message);
            return 1;
        }
    }

    private static async Task Prepare(PreparationJob job)
    {
        var settings = job.Settings;
        var arguments = new List<string> { "--ignore-config", "--no-plugins-cache", "--no-media-library", "--no-metadata-network-access",
            "--aout=dummy", "--vout=dummy", "--file-logging", "--logfile=" + job.Output + ".vlc.log", "--verbose=2" };
        if (job.BurnSubtitles)
        {
            var margin = settings.SubtitlePosition switch { "bottom" => -32768, "top" => 32768, _ => settings.SubtitleOffset };
            arguments.AddRange(["--sub-margin=" + Number(margin), "--freetype-font=" + settings.Font,
                "--freetype-fontsize=" + Number(settings.FontSize), settings.Bold ? "--freetype-bold" : "--no-freetype-bold",
                "--freetype-color=" + uint.Parse(settings.Color, NumberStyles.HexNumber, CultureInfo.InvariantCulture).ToString(CultureInfo.InvariantCulture),
                "--freetype-outline-thickness=" + Number(settings.Outline)]);
        }
        var instance = NewInstance(arguments);
        if (instance == IntPtr.Zero) throw new IOException("Installed LibVLC did not initialize.");
        IntPtr media = IntPtr.Zero, player = IntPtr.Zero;
        try
        {
            media = libvlc_media_new_path(instance, job.Input);
            if (media == IntPtr.Zero) throw new IOException("VLC could not open the source media.");
            var tracks = await Inspect(media);
            if (job.BurnSubtitles && !tracks.Any(track => track.Type == 2 && track.Index == job.SubtitleTrack))
                throw new IOException("The selected embedded subtitle track does not exist.");
            var selected = tracks.FirstOrDefault(track => track.Type == 0 &&
                track.Language.ToLowerInvariant() is "en" or "eng" or "english" &&
                (settings.AudioPreference == "dolby" && track.Codec is "a52" or "eac3" ||
                 settings.AudioPreference == "aac" && track.Codec == "mp4a"));
            var destination = job.Output.Replace('\\', '/').Replace("'", "\\'", StringComparison.Ordinal);
            var chain = "standard{access=file,mux=avformat{mux=matroska},dst='" + destination + "'}";
            if (job.BurnSubtitles) chain = "transcode{vcodec=h264,venc=x264{preset=veryfast,crf=20},soverlay}:" + chain;
            libvlc_media_add_option(media, ":sout=#" + chain);
            libvlc_media_add_option(media, ":no-sout-keep");
            libvlc_media_add_option(media, ":no-sout-all");
            if (selected is not null) libvlc_media_add_option(media, ":audio-track=" + Number(selected.Index));
            if (job.BurnSubtitles)
            {
                libvlc_media_add_option(media, ":sub-track=" + Number(job.SubtitleTrack));
                libvlc_media_add_option(media, ":spu");
                libvlc_media_add_option(media, ":sout-spu");
            }
            else libvlc_media_add_option(media, ":no-sout-spu");
            if (job.Seconds is { } duration) libvlc_media_add_option(media, ":stop-time=" + duration.ToString(CultureInfo.InvariantCulture));
            player = libvlc_media_player_new_from_media(media);
            if (player == IntPtr.Zero || libvlc_media_player_play(player) != 0) throw new IOException("VLC could not start preparation.");
            var timer = Stopwatch.StartNew();
            int state;
            while ((state = libvlc_media_player_get_state(player)) is not (6 or 7) && timer.Elapsed.TotalSeconds < job.TimeoutSeconds)
                await Task.Delay(50);
            libvlc_media_player_stop(player); // Flush the muxer before inspecting the output.
            if (state != 6) throw new IOException(state == 7 ? "VLC preparation failed; see the preparation log." : "VLC preparation timed out.");
            if (!File.Exists(job.Output) || new FileInfo(job.Output).Length == 0) throw new IOException("VLC produced no output.");
            var outputMedia = libvlc_media_new_path(instance, job.Output);
            if (outputMedia == IntPtr.Zero) throw new IOException("VLC could not inspect the prepared output.");
            List<Track> outputTracks;
            try { outputTracks = await Inspect(outputMedia); }
            finally { libvlc_media_release(outputMedia); }
            foreach (var type in new[] { 0, 1 })
                if (tracks.Any(track => track.Type == type) && !outputTracks.Any(track => track.Type == type))
                    throw new IOException("VLC output is missing " + (type == 0 ? "audio" : "video") + "; it will not be published.");
            var result = new { Engine = "LibVLC via .NET", job.Input, job.Output, job.BurnSubtitles, job.SubtitleTrack, job.Seconds,
                Settings = settings, SelectedAudio = selected, SourceTracks = tracks, OutputTracks = outputTracks,
                Bytes = new FileInfo(job.Output).Length, ElapsedSeconds = timer.Elapsed.TotalSeconds };
            await File.WriteAllTextAsync(job.Output + ".result.json", JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
            Console.WriteLine("VLC preparation completed and validated.");
        }
        finally
        {
            if (player != IntPtr.Zero) { libvlc_media_player_stop(player); libvlc_media_player_release(player); }
            if (media != IntPtr.Zero) libvlc_media_release(media);
            libvlc_release(instance);
        }
    }

    private static string Number(int value) => value.ToString(CultureInfo.InvariantCulture);
    private static IntPtr NewInstance(List<string> arguments)
    {
        var values = arguments.Select(Marshal.StringToCoTaskMemUTF8).ToArray();
        var argv = Marshal.AllocHGlobal(values.Length * IntPtr.Size);
        try
        {
            Marshal.Copy(values, 0, argv, values.Length);
            return libvlc_new(values.Length, argv);
        }
        finally { Marshal.FreeHGlobal(argv); foreach (var value in values) Marshal.FreeCoTaskMem(value); }
    }

    private static async Task<List<Track>> Inspect(IntPtr media)
    {
        if (libvlc_media_parse_with_options(media, 0, 10000) != 0) throw new IOException("VLC could not inspect this file.");
        var timer = Stopwatch.StartNew();
        while (libvlc_media_get_parsed_status(media) == 0 && timer.Elapsed.TotalSeconds < 12) await Task.Delay(20);
        if (libvlc_media_get_parsed_status(media) != 4) throw new IOException("VLC media inspection failed or timed out.");
        var count = libvlc_media_tracks_get(media, out var array);
        var tracks = new List<Track>();
        try
        {
            var indices = new Dictionary<int, int>();
            for (var i = 0; i < count; i++)
            {
                var track = Marshal.PtrToStructure<NativeTrack>(Marshal.ReadIntPtr(array, i * IntPtr.Size));
                var index = indices.GetValueOrDefault(track.Type);
                indices[track.Type] = index + 1;
                NativeAudio? audio = track.Type == 0 && track.Details != IntPtr.Zero ? Marshal.PtrToStructure<NativeAudio>(track.Details) : null;
                var codec = new byte[] { (byte)track.Codec, (byte)(track.Codec >> 8), (byte)(track.Codec >> 16), (byte)(track.Codec >> 24) };
                tracks.Add(new(track.Type, index, track.Id, Encoding.ASCII.GetString(codec).Trim(),
                    Marshal.PtrToStringUTF8(track.Language) ?? "", Marshal.PtrToStringUTF8(track.Description) ?? "", audio?.Channels, audio?.Rate));
            }
        }
        finally { libvlc_media_tracks_release(array, count); }
        return tracks;
    }

    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool SetDefaultDllDirectories(uint flags);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr AddDllDirectory(string directory);
    [DllImport("kernel32.dll")] private static extern bool RemoveDllDirectory(IntPtr cookie);
    [DllImport(Vlc, CallingConvention = CallingConvention.Cdecl)] private static extern IntPtr libvlc_new(int count, IntPtr arguments);
    [DllImport(Vlc, CallingConvention = CallingConvention.Cdecl)] private static extern void libvlc_release(IntPtr instance);
    [DllImport(Vlc, CallingConvention = CallingConvention.Cdecl)] private static extern IntPtr libvlc_media_new_path(IntPtr instance, [MarshalAs(UnmanagedType.LPUTF8Str)] string path);
    [DllImport(Vlc, CallingConvention = CallingConvention.Cdecl)] private static extern void libvlc_media_add_option(IntPtr media, [MarshalAs(UnmanagedType.LPUTF8Str)] string option);
    [DllImport(Vlc, CallingConvention = CallingConvention.Cdecl)] private static extern void libvlc_media_release(IntPtr media);
    [DllImport(Vlc, CallingConvention = CallingConvention.Cdecl)] private static extern int libvlc_media_parse_with_options(IntPtr media, int flags, int timeout);
    [DllImport(Vlc, CallingConvention = CallingConvention.Cdecl)] private static extern int libvlc_media_get_parsed_status(IntPtr media);
    [DllImport(Vlc, CallingConvention = CallingConvention.Cdecl)] private static extern uint libvlc_media_tracks_get(IntPtr media, out IntPtr tracks);
    [DllImport(Vlc, CallingConvention = CallingConvention.Cdecl)] private static extern void libvlc_media_tracks_release(IntPtr tracks, uint count);
    [DllImport(Vlc, CallingConvention = CallingConvention.Cdecl)] private static extern IntPtr libvlc_media_player_new_from_media(IntPtr media);
    [DllImport(Vlc, CallingConvention = CallingConvention.Cdecl)] private static extern void libvlc_media_player_release(IntPtr player);
    [DllImport(Vlc, CallingConvention = CallingConvention.Cdecl)] private static extern int libvlc_media_player_play(IntPtr player);
    [DllImport(Vlc, CallingConvention = CallingConvention.Cdecl)] private static extern void libvlc_media_player_stop(IntPtr player);
    [DllImport(Vlc, CallingConvention = CallingConvention.Cdecl)] private static extern int libvlc_media_player_get_state(IntPtr player);
}
