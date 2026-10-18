param([ValidateSet('folder','icon')][string]$Kind, [string]$DiagnosticLog)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
function Write-Diagnostic([string]$Message) {
    if ($DiagnosticLog) { Add-Content -LiteralPath $DiagnosticLog -Value ("{0:o} {1}" -f [DateTime]::UtcNow,$Message) -Encoding UTF8 }
}
Write-Diagnostic ("Starting {0} chooser; interactive={1}; apartment={2}" -f $Kind,[Environment]::UserInteractive,[Threading.Thread]::CurrentThread.ApartmentState)
if ($Kind -eq 'folder') {
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = 'Choose a folder to share. Files stay in their original locations.'
    $dialog.ShowNewFolderButton = $false
} else {
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = 'Choose the media server icon'
    $dialog.Filter = 'Images|*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.ico'
}
$owner = New-Object System.Windows.Forms.Form
$owner.Text = if ($Kind -eq 'folder') { 'Library Share - Choose folder' } else { 'Library Share - Choose icon' }
$owner.Size = New-Object Drawing.Size(440,110)
$owner.StartPosition = [Windows.Forms.FormStartPosition]::CenterScreen
$owner.FormBorderStyle = [Windows.Forms.FormBorderStyle]::FixedDialog
$owner.MinimizeBox = $false
$owner.MaximizeBox = $false
$owner.ShowInTaskbar = $true
$owner.TopMost = $true
$label = New-Object System.Windows.Forms.Label
$label.Text = 'Choose an item in the selection window, or cancel to return to VLC.'
$label.AutoSize = $false
$label.Dock = [Windows.Forms.DockStyle]::Fill
$label.TextAlign = [Drawing.ContentAlignment]::MiddleCenter
$owner.Controls.Add($label)
try {
    # The helper has no foreground window. An ownerless common dialog can end
    # up behind VLC without a usable taskbar entry. Give it an explicit visible
    # topmost owner and pass that owner to the native common dialog.
    $owner.Show()
    $owner.BringToFront()
    [void]$owner.Activate()
    Write-Diagnostic ("Owner shown; visible={0}; topmost={1}" -f $owner.Visible,$owner.TopMost)
    if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        if ($Kind -eq 'folder') { [Console]::Write($dialog.SelectedPath) }
        else { [Console]::Write($dialog.FileName) }
        Write-Diagnostic 'Selection completed.'
    } else {
        Write-Diagnostic 'Selection cancelled.'
    }
} catch {
    Write-Diagnostic ("Chooser failed: " + $_.Exception.Message)
    throw
} finally {
    $dialog.Dispose()
    $owner.Close()
    $owner.Dispose()
}
