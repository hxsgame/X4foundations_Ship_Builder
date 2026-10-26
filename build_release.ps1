# 发布打包：白名单复制 → 敏感信息校验 → 压缩 zip
# 用法：.\build_release.ps1  [-Version 20261025] [-OutDir "输出目录"]
# 特点：只打白名单文件，builder_config.json / 测试脚本 / cache 永远不会进包。

param(
    [string]$Version = (Get-Date -Format "yyyyMMdd"),
    [string]$OutDir  = (Join-Path $PSScriptRoot "dist")
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# 白名单：包内文件名 -> 仓库内源文件
# 注意：不放 .bat/.ps1/.exe 等可执行类型（N 网自动安检会隔离含脚本的包）；
#       启动方式改为双击 server.py（server 内已内置自动开浏览器与端口占用处理）。
$manifest = [ordered]@{
    "server.py"    = "server.py"
    "x4_lookup.py" = "x4_lookup.py"
    "index.html"   = "index.html"
    "使用说明.txt"  = "release\使用说明.txt"
}

$stage = Join-Path $env:TEMP ("x4sb_release_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $stage -Force | Out-Null

try {
    foreach ($name in $manifest.Keys) {
        $src = Join-Path $root $manifest[$name]
        if (-not (Test-Path $src)) { throw "缺少源文件: $src" }
        Copy-Item $src (Join-Path $stage $name)
    }

    # 校验 1：禁止文件不得出现在包里
    $forbidden = @("builder_config.json", ".gitignore", "backup_workdir_to_D.ps1")
    $hit = Get-ChildItem $stage -Recurse -File | Where-Object { $forbidden -contains $_.Name }
    if ($hit) { throw ("发布包混入禁止文件: " + ($hit.Name -join ", ")) }

    # 校验 2：扫描本机敏感路径特征
    $patterns = @("X4 exout", "UP7_Real_EVE_Ships", "TraeCN", "15536", "D:/Games", "D:\\Games")
    foreach ($f in Get-ChildItem $stage -Recurse -File) {
        $text = [IO.File]::ReadAllText($f.FullName, [Text.UTF8Encoding]::new($false))
        if (-not $text) { continue }
        foreach ($pat in $patterns) {
            if ($text.Contains($pat)) { throw "敏感信息命中: 文件 $($f.Name) 含「$pat」" }
        }
    }

    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    $zip = Join-Path $OutDir ("X4foundations_Ship_Builder_" + $Version + ".zip")
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    # 杀毒软件可能短暂占用刚复制的文件，压缩失败时重试 3 次
    $ok = $false
    for ($i = 1; $i -le 3 -and -not $ok; $i++) {
        try {
            [IO.Compression.ZipFile]::CreateFromDirectory($stage, $zip, [IO.Compression.CompressionLevel]::Optimal, $false)
            $ok = $true
        } catch {
            if ($i -eq 3) { throw }
            Start-Sleep -Seconds 2
        }
    }

    $info = Get-Item $zip
    Write-Host ""
    Write-Host ("[完成] " + $zip) -ForegroundColor Green
    Write-Host ("        大小 {0:N1} KB，文件 {1} 个" -f ($info.Length / 1KB), $manifest.Count)
    Get-ChildItem $stage -File | ForEach-Object { Write-Host ("        " + $_.Name) }
}
finally {
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
}
