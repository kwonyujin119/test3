# 유진·아름 사진 저장소 — 한 번에 정리하고 켜기 (fix.bat이 실행)
#  1) 돌고 있는 앨범 서버·터널을 멈춤
#  2) D 드라이브(없으면 내 문서)에 표준 폴더 D:\사진저장소 를 만들고 이 ZIP의 최신 파일을 넣음
#  3) PC 안의 다른 앨범 서버 폴더를 모두 찾아 사진 파일·목록(album.db)·설정(config.json)·cloudflared.exe 를 표준 폴더로 "복사"(원본은 지우지 않음)
#  4) 표준 폴더에서 서버를 켬 → 서버가 목록에 없는 사진을 스스로 되살림
$ErrorActionPreference = 'Continue'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path          # 이 파일이 있는 server 폴더(ZIP을 푼 곳)
$ZipRoot = Split-Path -Parent $Here                                  # index.html 이 있는 폴더
$Drive = if (Test-Path 'D:\') { 'D:\' } else { [Environment]::GetFolderPath('MyDocuments') + '\' }
$Root = Join-Path $Drive '사진저장소'
$Target = Join-Path $Root 'server'
Write-Host ''
Write-Host '====================================================='
Write-Host ' 유진·아름 사진 저장소 — 정리하고 켜기'
Write-Host " 표준 폴더: $Root"
Write-Host '====================================================='

# 1) 서버·터널 멈추기 (앨범 것만: 명령줄에 album_server.py / 127.0.0.1:4848 이 있는 것)
Write-Host '[1/4] 돌고 있는 앨범 서버를 멈춥니다...'
Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -like '*album_server.py*') -or ($_.CommandLine -like '*127.0.0.1:4848*') } | ForEach-Object {
  try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host "   멈춤: $($_.Name) (PID $($_.ProcessId))" } catch {}
}
Start-Sleep -Seconds 2

# 2) 표준 폴더 만들고 최신 파일 넣기
Write-Host '[2/4] 표준 폴더에 최신 파일을 넣습니다...'
New-Item -ItemType Directory -Force -Path $Target, (Join-Path $Target 'data'), (Join-Path $Target '사진') | Out-Null
foreach ($f in @('index.html', 'manifest.webmanifest', 'sw.js')) { if (Test-Path (Join-Path $ZipRoot $f)) { Copy-Item (Join-Path $ZipRoot $f) $Root -Force } }
foreach ($d in @('icons', 'img')) { if (Test-Path (Join-Path $ZipRoot $d)) { New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null; Copy-Item (Join-Path $ZipRoot ($d + '\*')) (Join-Path $Root $d) -Recurse -Force } }
foreach ($f in @('album_server.py', 'start.bat', 'set-code.bat', 'github-token-setup.bat', 'autostart-setup.bat', 'fix.bat', 'fix.ps1', 'README.md')) { if (Test-Path (Join-Path $Here $f)) { Copy-Item (Join-Path $Here $f) $Target -Force } }

# 3) 다른 앨범 서버 폴더 찾기 (D:\ 와 사용자 폴더, 깊이 제한)
Write-Host '[3/4] PC 안의 다른 앨범 서버 폴더를 찾아 사진과 목록을 모읍니다...'
# 찾는 곳: D:\(깊이 5), 바탕화면·다운로드·문서(깊이 4). AppData 같은 큰 폴더는 건너뛴다(오래 걸림)
$roots = @()
if (Test-Path 'D:\') { $roots += @{ p = 'D:\'; d = 5 } }
foreach ($sp in @('Desktop', 'MyDocuments')) { $roots += @{ p = [Environment]::GetFolderPath($sp); d = 4 } }
$roots += @{ p = (Join-Path ([Environment]::GetFolderPath('UserProfile')) 'Downloads'); d = 4 }
$found = @()
foreach ($r in $roots) {
  if (-not (Test-Path $r.p)) { continue }
  Write-Host "   살펴보는 중: $($r.p)"
  try {
    Get-ChildItem -Path $r.p -Filter 'album_server.py' -Recurse -Depth $r.d -File -ErrorAction SilentlyContinue | ForEach-Object {
      $dir = $_.DirectoryName
      if ($dir -ne $Target -and $dir -ne $Here) { $script:found += $dir }
    }
  } catch {}
}
$found = $found | Sort-Object -Unique
$copied = 0; $dbPicked = ''; $dbSize = 0; $cfgPicked = ''
function Get-PhotosDir($srvDir) {
  $cfg = Join-Path $srvDir 'data\config.json'
  if (Test-Path $cfg) {
    try { $j = Get-Content $cfg -Raw -Encoding UTF8 | ConvertFrom-Json; if ($j.photos_dir -and (Test-Path $j.photos_dir)) { return $j.photos_dir } } catch {}
  }
  return (Join-Path $srvDir '사진')
}
# 표준 폴더 자신이 예전부터 쓰던 곳이면 그 사진 폴더(설정상 다른 위치일 수 있음)도 후보에
$targetPhotos = Get-PhotosDir $Target
foreach ($dir in $found) {
  $photos = Get-PhotosDir $dir
  $n = 0
  if (Test-Path $photos) {
    $n = @(Get-ChildItem -Path $photos -File -Recurse -Depth 1 -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^[a-f0-9]{24}$' }).Count
  }
  Write-Host "   찾음: $dir  (사진 파일 $n개)"
  if ($n -gt 0 -and $photos -ne $targetPhotos) {
    # 사진 파일 복사(있는 파일은 건너뜀, 하위 폴더 유지)
    Get-ChildItem -Path $photos -Recurse -Depth 1 -File -ErrorAction SilentlyContinue | ForEach-Object {
      $rel = $_.FullName.Substring($photos.TrimEnd('\').Length).TrimStart('\')
      $dst = Join-Path $targetPhotos $rel
      if (-not (Test-Path $dst)) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
        Copy-Item $_.FullName $dst -ErrorAction SilentlyContinue
        $script:copied++
      }
    }
  }
  $db = Join-Path $dir 'data\album.db'
  if ((Test-Path $db) -and ((Get-Item $db).Length -gt $dbSize)) { $dbSize = (Get-Item $db).Length; $dbPicked = $db }
  $cfg = Join-Path $dir 'data\config.json'
  if (Test-Path $cfg) {
    $txt = Get-Content $cfg -Raw -ErrorAction SilentlyContinue
    if ($txt -and ($txt -like '*github_pat_*' -or -not $cfgPicked)) { $cfgPicked = $cfg }
  }
  $cf = Join-Path $dir 'cloudflared.exe'
  if ((Test-Path $cf) -and -not (Test-Path (Join-Path $Target 'cloudflared.exe'))) { Copy-Item $cf $Target -Force; Write-Host '   cloudflared.exe 가져옴' }
}
Write-Host "   사진 파일 $copied개를 표준 폴더로 복사했습니다."
# 목록(album.db): 표준 폴더에 없거나 더 작으면, 찾은 것 중 가장 큰 것을 가져온다(기존 것은 .bak 으로 보관)
$tdb = Join-Path $Target 'data\album.db'
if ($dbPicked) {
  $tsize = 0; if (Test-Path $tdb) { $tsize = (Get-Item $tdb).Length }
  if ($dbSize -gt $tsize) {
    if (Test-Path $tdb) { Copy-Item $tdb ($tdb + '.bak-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) -Force }
    Copy-Item $dbPicked $tdb -Force
    foreach ($suf in @('-wal', '-shm')) { $src = $dbPicked + $suf; if (Test-Path $src) { Copy-Item $src ($tdb + $suf) -Force } }
    Write-Host "   사진 목록 가져옴: $dbPicked"
  }
}
# 설정(config.json): 표준 폴더에 없을 때만 가져온다(토큰·접속코드 보존)
$tcfg = Join-Path $Target 'data\config.json'
if ($cfgPicked -and -not (Test-Path $tcfg)) { Copy-Item $cfgPicked $tcfg -Force; Write-Host "   설정 가져옴: $cfgPicked" }
# 설정의 photos_dir 가 다른 곳을 가리키면 표준 사진 폴더로 돌린다(복사해 두었으므로)
if (Test-Path $tcfg) {
  try {
    $j = Get-Content $tcfg -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($j.photos_dir -and ($j.photos_dir -ne (Join-Path $Target '사진'))) {
      # 그 폴더의 사진도 표준 폴더로 복사
      if (Test-Path $j.photos_dir) {
        Get-ChildItem -Path $j.photos_dir -Recurse -Depth 1 -File -ErrorAction SilentlyContinue | ForEach-Object {
          $rel = $_.FullName.Substring($j.photos_dir.TrimEnd('\').Length).TrimStart('\'); $dst = Join-Path (Join-Path $Target '사진') $rel
          if (-not (Test-Path $dst)) { New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null; Copy-Item $_.FullName $dst -ErrorAction SilentlyContinue }
        }
      }
      $j.photos_dir = (Join-Path $Target '사진')
      [IO.File]::WriteAllText($tcfg, ($j | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding $false))   # BOM 없이(서버가 읽음)
    }
  } catch {}
}

# 4) 켜기
Write-Host '[4/4] 서버를 켭니다...'
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', ('start "" "' + (Join-Path $Target 'start.bat') + '"') -WorkingDirectory $Target
Start-Sleep -Seconds 10
try { Start-Process 'http://localhost:4848/status' } catch {}
Write-Host ''
Write-Host '====================================================='
Write-Host ' 끝. 새 검은 창(서버)이 떠 있고, 브라우저에 상태 화면이 열립니다.'
Write-Host ' 상태 화면의 "목록의 사진 / 폴더 안 파일" 숫자를 확인하세요.'
Write-Host " 앞으로는 $Target\start.bat 로 켜면 됩니다. 예전 폴더는 그대로 두었습니다(확인 뒤 지워도 됨)."
Write-Host '====================================================='
