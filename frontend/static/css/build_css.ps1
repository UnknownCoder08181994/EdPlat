$cssDir = 'C:\Users\Shane\Desktop\OIT\frontend\static\css'
$outputFile = Join-Path $cssDir 'main.built.css'
$files = @(
    'variables.css',
    'reset.css',
    'layout.css',
    'typography.css',
    'nav.css',
    'fullpage/scroll.css',
    'fullpage/transitions.css',
    'fullpage/dots.css',
    'hero/backgrounds.css',
    'hero/content.css',
    'hero/text.css',
    'hero/terminal.css',
    'hero/misc.css',
    'humanoid/section.css',
    'humanoid/header.css',
    'humanoid/glitch.css',
    'humanoid/cards-layout.css',
    'humanoid/lab-environment.css',
    'humanoid/card-base.css',
    'humanoid/card-frame.css',
    'humanoid/card-body.css',
    'humanoid/card-status.css',
    'humanoid/card-typography.css',
    'humanoid/card-hover.css',
    'humanoid/v3-upgrades.css',
    'faq/programs-section.css',
    'faq/programs-cards.css',
    'faq/programs-previews.css',
    'standalone.css',
    'modules/catalog.css',
    'modules/filters.css',
    'modules/toolbar.css',
    'modules/cards.css',
    'modules/card-fx.css',
    'modules/learning-paths.css',
    'faq/section.css',
    'faq/cards.css',
    'chat/layout.css',
    'chat/messages.css',
    'chat/input.css',
    'hamburger.css',
    'module-detail/hero.css',
    'module-detail/body.css',
    'module-detail/sidebar.css',
    'module-viewer/layout.css',
    'module-viewer/chat.css',
    'module-viewer/video.css',
    'module-viewer/topics.css',
    'responsive.css'
)
$sb = [System.Text.StringBuilder]::new()
[void]$sb.AppendLine("/* ==========================================================================")
[void]$sb.AppendLine("   main.built.css - Auto-generated concatenated CSS")
[void]$sb.AppendLine("   Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
[void]$sb.AppendLine("   Source: main.css @import statements")
[void]$sb.AppendLine("   ========================================================================== */")
[void]$sb.AppendLine("")
$totalFiles = 0
$missingFiles = @()
foreach ($file in $files) {
    $fullPath = Join-Path $cssDir $file
    if (Test-Path $fullPath) {
        $totalFiles++
        [void]$sb.AppendLine("/* ==========================================================================")
        [void]$sb.AppendLine("   Source: $file")
        [void]$sb.AppendLine("   ========================================================================== */")
        $content = [System.IO.File]::ReadAllText($fullPath, [System.Text.Encoding]::UTF8)
        [void]$sb.AppendLine($content)
        [void]$sb.AppendLine("")
    } else {
        $missingFiles += $file
        Write-Warning "File not found: $fullPath"
    }
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($outputFile, $sb.ToString(), $utf8NoBom)
Write-Host ""
Write-Host "Build complete!"
Write-Host "  Output: $outputFile"
Write-Host "  Files concatenated: $totalFiles / $($files.Count)"
$outputSize = (Get-Item $outputFile).Length
Write-Host "  Output size: $([math]::Round($outputSize / 1024, 2)) KB ($outputSize bytes)"
if ($missingFiles.Count -gt 0) {
    Write-Host ""
    Write-Host "WARNING: $($missingFiles.Count) file(s) were missing:"
    foreach ($mf in $missingFiles) {
        Write-Host "  - $mf"
    }
}