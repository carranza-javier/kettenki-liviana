<#
.SYNOPSIS
    Packages and deploys the contact-form stack.

.DESCRIPTION
    Same shape as deploy.ps1, one stack smaller. Four idempotent steps:
      1. make sure the artifact bucket exists (holds the function zip)
      2. zip src/contact and upload it under a content-addressed key
      3. deploy infra/contact.yaml
      4. print the stack outputs

    Re-run after any change. A code change produces a new zip key, which is
    what makes CloudFormation notice the function needs updating.

    BEFORE THE FIRST RUN: the sender address must be a verified SES identity in
    this region, and while SES is in the sandbox the recipient must be verified
    too. Both are the same inbox here, so one verification covers it:

        aws sesv2 create-email-identity --email-identity info@kettenki.com --region eu-central-1

    That sends a confirmation link to the inbox. Until someone clicks it, every
    send is rejected and the form reports a failure. Leaving the sandbox is NOT
    required: it only restricts sending to unverified recipients, and the only
    recipient here is our own address.

.EXAMPLE
    ./scripts/deploy-contact.ps1 -ArtifactBucketName kettenki-liviana-artifacts `
                                 -SenderAddress info@kettenki.com `
                                 -RecipientAddress info@kettenki.com `
                                 -AllowedOrigin https://kettenki.com
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ArtifactBucketName,
    [Parameter(Mandatory = $true)][string]$SenderAddress,
    [Parameter(Mandatory = $true)][string]$RecipientAddress,
    [Parameter(Mandatory = $true)][string]$AllowedOrigin,
    [string]$StackName = "kettenki-contact",
    [string]$ProjectName = "kettenki-contact",
    [string]$Region = "eu-central-1"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot

# 1. Artefakt-Eimer -----------------------------------------------------------
try {
    aws s3api head-bucket --bucket $ArtifactBucketName --region $Region 2>$null | Out-Null
} catch {
    Write-Host "Creating artifact bucket $ArtifactBucketName"
    aws s3api create-bucket --bucket $ArtifactBucketName --region $Region `
        --create-bucket-configuration LocationConstraint=$Region | Out-Null
}

# 2. Funktion packen ----------------------------------------------------------
$staging = Join-Path ([System.IO.Path]::GetTempPath()) ("contact-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $staging | Out-Null
Copy-Item (Join-Path $repo "src/contact/*") $staging -Recurse
$zip = Join-Path ([System.IO.Path]::GetTempPath()) ("contact-" + [guid]::NewGuid() + ".zip")
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zip

# Der Schlüssel trägt den Hash des Inhalts. Gleicher Code, gleicher Schlüssel,
# und CloudFormation lässt die Funktion in Ruhe; geänderter Code, neuer
# Schlüssel, und sie wird ausgetauscht.
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.Substring(0, 16).ToLower()
$key = "contact/$hash.zip"
aws s3 cp $zip "s3://$ArtifactBucketName/$key" --region $Region | Out-Null
Remove-Item $zip, $staging -Recurse -Force

# 3. Stack ausrollen ----------------------------------------------------------
aws cloudformation deploy `
    --template-file (Join-Path $repo "infra/contact.yaml") `
    --stack-name $StackName `
    --region $Region `
    --capabilities CAPABILITY_NAMED_IAM `
    --parameter-overrides `
        ProjectName=$ProjectName `
        AllowedOrigin=$AllowedOrigin `
        SenderAddress=$SenderAddress `
        RecipientAddress=$RecipientAddress `
        ArtifactBucket=$ArtifactBucketName `
        ArtifactKey=$key

# 4. Ausgaben -----------------------------------------------------------------
Write-Host ""
Write-Host "Stack outputs:"
aws cloudformation describe-stacks --stack-name $StackName --region $Region `
    --query "Stacks[0].Outputs" --output table

Write-Host ""
Write-Host "Die Endpoint-URL oben gehoert in ENDPOINT in js/contact-form.js"
Write-Host "im Repo kettenKI-website. Bis sie dort steht, oeffnet das Formular"
Write-Host "weiterhin eine vorbereitete E-Mail, statt zu senden."
