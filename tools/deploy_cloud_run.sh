#!/bin/bash
# Deploy the Marswalk API to Google Cloud Run and check it. Run in Cloud Shell, from the api_bundle folder.
#
#   REGION=us-east1 bash tools/deploy_cloud_run.sh            # private service (default)
#   REGION=us-east1 PUBLIC=yes bash tools/deploy_cloud_run.sh # public: ONLY if project policy allows and the team agrees
#
# Before running: confirm with Valeria / the project admin that the hackathon credits cover
# Cloud Run, Cloud Build and Artifact Registry, and which region is allowed.
# Never paste Google credentials or ADC files in the team chat or in Base44.
set -euo pipefail

PROJECT="${PROJECT:-project-480d8e7f-79f8-45b3-951}"
SERVICE="${SERVICE:-jezero-marswalk-api}"
REGION="${REGION:?Set REGION, for example REGION=us-east1 (ask Valeria which region the project allows)}"
# The app origins allowed by CORS. marseva.us is added once the domain works (it is harmless before).
ORIGINS="${ORIGINS:-https://jolly-mars-path-pilot.base44.app}"

[ -f api/main.py ] && [ -f Dockerfile ] || { echo "Run this from the api_bundle folder"; exit 1; }

echo "== project $PROJECT, region $REGION, service $SERVICE"
gcloud config set project "$PROJECT"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

AUTH="--no-allow-unauthenticated"
[ "${PUBLIC:-no}" = "yes" ] && AUTH="--allow-unauthenticated"

# ^@^ changes gcloud's list separator, so the commas between origins stay inside one value
gcloud run deploy "$SERVICE" --source . --region "$REGION" \
  --memory 1Gi --cpu 1 --min-instances 0 --max-instances 3 --timeout 120 \
  --set-env-vars "^@^CORS_ORIGINS=$ORIGINS" $AUTH

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')
echo "== deployed: $URL"

TOKEN_ARG=()
if [ "$AUTH" = "--no-allow-unauthenticated" ]; then
  echo "== private service: checking with your identity token (Base44 cannot call a private URL directly)"
  TOKEN_ARG=(--token "$(gcloud auth print-identity-token)")
fi
python3 tools/check_live_api.py "$URL" --origins "$ORIGINS" "${TOKEN_ARG[@]}"
echo "== all checks passed. Give this URL to the app: $URL"
