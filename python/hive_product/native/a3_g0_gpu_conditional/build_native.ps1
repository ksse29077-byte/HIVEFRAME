[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExecutable,

    [Parameter(Mandatory = $true)]
    [string]$BuildRoot
)

$ErrorActionPreference = 'Stop'

$sourceRoot = $PSScriptRoot
$cudaRoot = $env:CUDA_PATH
if (-not $cudaRoot -or -not (Test-Path -LiteralPath (Join-Path $cudaRoot 'bin\nvcc.exe'))) {
    throw 'CUDA_PATH must identify the admitted CUDA Toolkit before building A3-G0.'
}
if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
    throw 'Run this script from an x64 Visual C++ developer environment.'
}

$metadataCode = @'
import json
import sys
import sysconfig
from pathlib import Path

print(json.dumps({
    "include_paths": [sysconfig.get_paths()["include"]],
    "library_paths": [str(Path(sys.base_prefix) / "libs")],
    "python_library": f"python{sys.version_info.major}{sys.version_info.minor}.lib",
}))
'@
$metadataEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($metadataCode))
$metadataBootstrap = "import base64;exec(base64.b64decode('$metadataEncoded'))"
$metadata = (& $PythonExecutable -c $metadataBootstrap | ConvertFrom-Json)
if ($LASTEXITCODE -ne 0) {
    throw 'Unable to query PyTorch extension build metadata.'
}

$build = [System.IO.Path]::GetFullPath($BuildRoot)
New-Item -ItemType Directory -Force -Path $build | Out-Null
$bindingObject = Join-Path $build 'binding.obj'
$cudaObject = Join-Path $build 'conditional_omission.obj'
$modulePath = Join-Path $build 'hiveframe_a3_g0_cuda.pyd'

$bindingIncludes = @("/I$sourceRoot", "/I$(Join-Path $cudaRoot 'include')")
$bindingIncludes += $metadata.include_paths | ForEach-Object { "/I$_" }
$bindingArgs = @(
    '/nologo', '/c', '/O2', '/MD', '/EHsc', '/std:c++17', '/utf-8',
    '/DTORCH_API_INCLUDE_EXTENSION_H',
    '/DTORCH_EXTENSION_NAME=hiveframe_a3_g0_cuda'
) + $bindingIncludes + @(
    (Join-Path $sourceRoot 'binding.cpp'),
    "/Fo$bindingObject"
)
& cl.exe @bindingArgs
if ($LASTEXITCODE -ne 0) {
    throw "binding.cpp compilation failed with exit code $LASTEXITCODE"
}

$cudaArgs = @(
    '-c', '-O2', '-std=c++17', '-arch=sm_86', '--use-local-env',
    '-Xcompiler=/MD', '-Xcompiler=/EHsc', '-Xcompiler=/utf-8',
    "-I$sourceRoot",
    (Join-Path $sourceRoot 'conditional_omission.cu'),
    '-o', $cudaObject
)
& (Join-Path $cudaRoot 'bin\nvcc.exe') @cudaArgs
if ($LASTEXITCODE -ne 0) {
    throw "conditional_omission.cu compilation failed with exit code $LASTEXITCODE"
}

$libraryArgs = @("/LIBPATH:$(Join-Path $cudaRoot 'lib\x64')")
$libraryArgs += $metadata.library_paths | ForEach-Object { "/LIBPATH:$_" }
$linkArgs = @('/NOLOGO', '/DLL', '/INCREMENTAL:NO', $bindingObject, $cudaObject) +
    $libraryArgs + @(
        'cudart.lib', $metadata.python_library, "/OUT:$modulePath"
    )
& link.exe @linkArgs
if ($LASTEXITCODE -ne 0) {
    throw "native extension link failed with exit code $LASTEXITCODE"
}

Get-Item -LiteralPath $modulePath | Select-Object FullName, Length, LastWriteTime
