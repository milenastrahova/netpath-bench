# Run only self-generated UDP traffic inside an isolated Linux Docker namespace.
param([int]$Repetitions = 2, [int]$Count = 120)
$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
if (-not $repo) { throw 'Cannot locate repository directory from script path' }
if (-not (Test-Path (Join-Path $repo 'scripts\run_pcap_capture.py'))) { throw 'PCAP scripts missing; run git pull --ff-only' }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker not found on PATH' }
Push-Location $repo
try {
  docker info --format '{{.ServerVersion}}' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not running' }
  docker build -f Dockerfile.pcap -t netpath-pcap-evidence:local .
  if ($LASTEXITCODE -ne 0) { throw 'Docker image build failed' }
  docker run --rm --network none --cap-drop ALL --cap-add NET_RAW --cap-add NET_ADMIN --cap-add DAC_OVERRIDE -v "milenastrahova/netpath-bench:/work" -w /work netpath-pcap-evidence:local python scripts/run_pcap_capture.py --repetitions $Repetitions --count $Count
  if ($LASTEXITCODE -ne 0) { throw 'Capture failed. Check the output above; Windows network configuration is unchanged.' }
  Write-Host 'PASS: Evidence ZIP is in the reports directory.' -ForegroundColor Green
} finally { Pop-Location }
