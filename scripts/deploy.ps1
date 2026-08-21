<#
.SYNOPSIS
    Packages and deploys the Liviana stack.

.DESCRIPTION
    Five steps, all idempotent:
      1. make sure the artifact bucket exists (holds the function zip)
      2. zip src/liviana and upload it under a content-addressed key
      3. deploy infra/template.yaml
      4. upload the content document to the bucket the stack created
      5. print the stack outputs

    Re-run it after any change. A code change produces a new zip key, which is
    what makes CloudFormation notice the function needs updating.

.EXAMPLE
    ./scripts/deploy.ps1 -ContentBucketName kettenki-liviana-content `
                         -AlertEmail info@example.com `
                         -AllowedOrigin https://example.com
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ContentBucketName,
    [Parameter(Mandatory = $true)][string]$AlertEmail,
    [string]$AllowedOrigin = "*",
    [string]$StackName = "liviana",
    [string]$ProjectName = "liviana",
    [string]$Region = "eu-central-1",
    [string]$ModelId = "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
    [string]$ContentFile = "content/content.json",
    [string]$ContentKey = "content.json",
    [int]$RateLimitPerMinute = 20,
    [int]$DailyInvocationLimit = 500,
    [int]$ReservedConcurrency = 5,
    [int]$MonthlyBudgetUsd = 10,
    [string]$AwsProfile
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$awsCommon = @("--region", $Region)
if ($AwsProfile) { $awsCommon += @("--profile", $AwsProfile) }

function Invoke-Aws {
    param([string[]]$Arguments)
    $output = & aws @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "aws $($Arguments -join ' ') failed:`n$output"
    }
    return $output
}

Write-Host "==> Identity" -ForegroundColor Cyan
$identity = Invoke-Aws (@("sts", "get-caller-identity", "--output", "json") + $awsCommon) | ConvertFrom-Json
$accountId = $identity.Account
Write-Host "    account $accountId, region $Region"

# --- 1. artifact bucket ------------------------------------------------------
$artifactBucket = "$ProjectName-artifacts-$accountId-$Region"
Write-Host "==> Artifact bucket $artifactBucket" -ForegroundColor Cyan
& aws s3api head-bucket --bucket $artifactBucket @awsCommon 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "    creating"
    if ($Region -eq "us-east-1") {
        Invoke-Aws (@("s3api", "create-bucket", "--bucket", $artifactBucket) + $awsCommon) | Out-Null
    }
    else {
        Invoke-Aws (@("s3api", "create-bucket", "--bucket", $artifactBucket,
                "--create-bucket-configuration", "LocationConstraint=$Region") + $awsCommon) | Out-Null
    }
    Invoke-Aws (@("s3api", "put-public-access-block", "--bucket", $artifactBucket,
            "--public-access-block-configuration",
            "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true") + $awsCommon) | Out-Null
}

# --- 2. package --------------------------------------------------------------
Write-Host "==> Packaging" -ForegroundColor Cyan
$buildDir = Join-Path $repoRoot "build"
$stageDir = Join-Path $buildDir "stage"
Remove-Item -Recurse -Force $stageDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stageDir | Out-Null
Copy-Item -Recurse (Join-Path $repoRoot "src/liviana") (Join-Path $stageDir "liviana")
Get-ChildItem -Path $stageDir -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force

$zipPath = Join-Path $buildDir "liviana.zip"
Remove-Item -Force $zipPath -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $stageDir "liviana") -DestinationPath $zipPath

$hash = (Get-FileHash $zipPath -Algorithm SHA256).Hash.Substring(0, 12).ToLower()
$codeKey = "lambda/liviana-$hash.zip"
Write-Host "    $zipPath -> s3://$artifactBucket/$codeKey"
Invoke-Aws (@("s3", "cp", $zipPath, "s3://$artifactBucket/$codeKey") + $awsCommon) | Out-Null

# --- 3. deploy ---------------------------------------------------------------
Write-Host "==> Deploying stack $StackName" -ForegroundColor Cyan
$parameters = @(
    "ProjectName=$ProjectName",
    "ContentBucketName=$ContentBucketName",
    "ContentKey=$ContentKey",
    "AllowedOrigin=$AllowedOrigin",
    "ModelId=$ModelId",
    "LambdaCodeBucket=$artifactBucket",
    "LambdaCodeKey=$codeKey",
    "RateLimitPerMinute=$RateLimitPerMinute",
    "DailyInvocationLimit=$DailyInvocationLimit",
    "ReservedConcurrency=$ReservedConcurrency",
    "MonthlyBudgetUsd=$MonthlyBudgetUsd",
    "AlertEmail=$AlertEmail"
)
Invoke-Aws (@("cloudformation", "deploy",
        "--template-file", "infra/template.yaml",
        "--stack-name", $StackName,
        "--capabilities", "CAPABILITY_IAM",
        "--no-fail-on-empty-changeset",
        "--parameter-overrides") + $parameters + $awsCommon)

# --- 4. content --------------------------------------------------------------
Write-Host "==> Uploading content document" -ForegroundColor Cyan
python -c "import json,sys; json.load(open(sys.argv[1], encoding='utf-8'))" $ContentFile
if ($LASTEXITCODE -ne 0) { throw "$ContentFile is not valid JSON." }
Invoke-Aws (@("s3", "cp", $ContentFile, "s3://$ContentBucketName/$ContentKey",
        "--content-type", "application/json") + $awsCommon) | Out-Null

# --- 5. outputs --------------------------------------------------------------
Write-Host "==> Outputs" -ForegroundColor Cyan
$outputs = Invoke-Aws (@("cloudformation", "describe-stacks", "--stack-name", $StackName,
        "--query", "Stacks[0].Outputs", "--output", "json") + $awsCommon) | ConvertFrom-Json
foreach ($output in $outputs) {
    Write-Host ("    {0,-22} {1}" -f $output.OutputKey, $output.OutputValue)
}

Write-Host ""
Write-Host "Done. If this was the first deploy, confirm the SNS subscription email" -ForegroundColor Green
Write-Host "and check that Bedrock model access is enabled for $ModelId." -ForegroundColor Green
