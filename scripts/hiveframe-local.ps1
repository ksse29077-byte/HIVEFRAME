[CmdletBinding()]
param(
    [int]$Port = 8765,
    [string]$ArtifactRoot = "",
    [string]$PythonExecutable = "",
    [switch]$SmokeTest,
    [string]$BrowserSignalPath = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

function Stop-WithMessage([string]$Message) {
    Write-Host ""
    Write-Host "HIVEFRAME을 시작하지 못했습니다." -ForegroundColor Red
    Write-Host $Message -ForegroundColor Yellow
    exit 1
}

function Get-PythonCommand {
    if ($PythonExecutable) {
        if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
            Stop-WithMessage "Python을 찾을 수 없습니다. HIVEFRAME_PYTHON 또는 -PythonExecutable을 확인해주세요."
        }
        return @{ Command = (Resolve-Path -LiteralPath $PythonExecutable).Path; Prefix = @() }
    }
    if ($env:HIVEFRAME_PYTHON) {
        if (-not (Test-Path -LiteralPath $env:HIVEFRAME_PYTHON -PathType Leaf)) {
            Stop-WithMessage "HIVEFRAME_PYTHON에 지정된 Python을 찾을 수 없습니다."
        }
        return @{ Command = (Resolve-Path -LiteralPath $env:HIVEFRAME_PYTHON).Path; Prefix = @() }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @{ Command = $python.Source; Prefix = @() } }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return @{ Command = $py.Source; Prefix = @("-3") } }
    Stop-WithMessage "Python을 찾을 수 없습니다. 기존 Python 환경을 먼저 준비해주세요."
}

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$entrypoint = Join-Path $repositoryRoot "hiveframe_product.py"
$packageRoot = Join-Path $repositoryRoot "python"
if (-not (Test-Path -LiteralPath $entrypoint -PathType Leaf) -or -not (Test-Path -LiteralPath $packageRoot -PathType Container)) {
    Stop-WithMessage "HIVEFRAME 저장소 구조를 확인해주세요."
}

$requiredEnvironment = @("HIVEFRAME_COMFYUI_ROOT", "HIVEFRAME_H3_ASSET_ROOT", "HIVEFRAME_H3_WORKFLOW")
foreach ($name in $requiredEnvironment) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if (-not $value) { Stop-WithMessage "$name 설정이 필요합니다." }
}

if (-not (Test-Path -LiteralPath $env:HIVEFRAME_COMFYUI_ROOT -PathType Container)) {
    Stop-WithMessage "Local AI 실행 폴더를 찾을 수 없습니다. HIVEFRAME_COMFYUI_ROOT를 확인해주세요."
}
$comfyMain = Join-Path $env:HIVEFRAME_COMFYUI_ROOT "main.py"
$comfyPython = Join-Path $env:HIVEFRAME_COMFYUI_ROOT ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $comfyMain -PathType Leaf) -or -not (Test-Path -LiteralPath $comfyPython -PathType Leaf)) {
    Stop-WithMessage "Local AI 실행 환경이 완전하지 않습니다. main.py와 전용 Python을 확인해주세요."
}

if (-not (Test-Path -LiteralPath $env:HIVEFRAME_H3_ASSET_ROOT -PathType Container)) {
    Stop-WithMessage "모델 폴더를 찾을 수 없습니다. HIVEFRAME_H3_ASSET_ROOT를 확인해주세요."
}
$requiredModels = @(
    "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "minimax_h3_video_vae_fp16.safetensors",
    "minimax_h3_audio_vae_fp32.safetensors"
)
foreach ($model in $requiredModels) {
    if (-not (Test-Path -LiteralPath (Join-Path $env:HIVEFRAME_H3_ASSET_ROOT $model) -PathType Leaf)) {
        Stop-WithMessage "필요한 모델 파일을 확인해주세요: $model"
    }
}
if (-not (Test-Path -LiteralPath $env:HIVEFRAME_H3_WORKFLOW -PathType Leaf)) {
    Stop-WithMessage "필요한 영상 생성 설정 파일을 확인해주세요."
}

if (-not $ArtifactRoot) {
    $ArtifactRoot = if ($env:HIVEFRAME_ARTIFACT_ROOT) { $env:HIVEFRAME_ARTIFACT_ROOT } else { Join-Path $env:LOCALAPPDATA "HIVEFRAME\Alpha" }
}
try {
    New-Item -ItemType Directory -Path $ArtifactRoot -Force | Out-Null
    $probe = Join-Path $ArtifactRoot (".write-probe-" + [Guid]::NewGuid().ToString("N"))
    [IO.File]::WriteAllText($probe, "ok")
    Remove-Item -LiteralPath $probe -Force
} catch {
    Stop-WithMessage "결과 저장 폴더에 쓸 수 없습니다. HIVEFRAME_ARTIFACT_ROOT를 확인해주세요."
}
if (-not $env:HIVEFRAME_H3_OUTPUT_ROOT) {
    $env:HIVEFRAME_H3_OUTPUT_ROOT = Join-Path $ArtifactRoot "local-ai"
}

try {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    $listener.Start()
    $listener.Stop()
} catch {
    Stop-WithMessage "포트 $Port 을(를) 이미 사용 중입니다. 실행 중인 HIVEFRAME을 확인하거나 다른 포트를 지정해주세요."
}

$python = Get-PythonCommand
$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = if ($oldPythonPath) { "$packageRoot;$oldPythonPath" } else { $packageRoot }
try {
    & $python.Command @($python.Prefix) -c "import hive_product; from hive_product.service import ProductService" 2>$null
    if ($LASTEXITCODE -ne 0) { Stop-WithMessage "HIVEFRAME Python 모듈을 불러오지 못했습니다." }

    $arguments = @($python.Prefix) + @(
        $entrypoint, "--host", "127.0.0.1", "--port", $Port,
        "--artifact-root", $ArtifactRoot, "--start-local-runtime", "--open-browser"
    )
    if ($SmokeTest) { $arguments += "--smoke-test" }
    if ($BrowserSignalPath) { $arguments += @("--browser-signal-path", $BrowserSignalPath) }

    Write-Host "HIVEFRAME을 시작합니다..." -ForegroundColor Cyan
    & $python.Command @arguments
    if ($LASTEXITCODE -ne 0) { Stop-WithMessage "서버 시작에 실패했습니다. 위 안내를 확인해주세요." }
} finally {
    $env:PYTHONPATH = $oldPythonPath
}
