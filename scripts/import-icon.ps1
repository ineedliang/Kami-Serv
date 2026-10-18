param([Parameter(Mandatory=$true)][string]$Source, [Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
if ((Get-Item -LiteralPath $Source).Length -gt 20MB) { throw 'Choose an image smaller than 20 MB.' }
$image = [Drawing.Image]::FromFile($Source)
$bitmap = $null
$graphics = $null
try {
    $bitmap = New-Object Drawing.Bitmap(256,256)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    $graphics.Clear([Drawing.Color]::Transparent)
    $graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $scale = [Math]::Min(256.0/$image.Width,256.0/$image.Height)
    $width = [int]($image.Width*$scale); $height = [int]($image.Height*$scale)
    $graphics.DrawImage($image,[int]((256-$width)/2),[int]((256-$height)/2),$width,$height)
    $bitmap.Save($Destination,[Drawing.Imaging.ImageFormat]::Png)
} finally {
    if ($graphics) { $graphics.Dispose() }
    if ($bitmap) { $bitmap.Dispose() }
    $image.Dispose()
}
