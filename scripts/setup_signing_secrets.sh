#!/usr/bin/env bash
# Persistente Signier-Identitaet fuer die CI/CD-Kette registrieren.
#
# Warum dieses Skript? Der Bot-Token der Agent-Sandbox darf keine Repo-Secrets
# schreiben (HTTP 403). Mit DEINEM gh-Login (Scope admin:repo) laeuft es einmal:
#
#   ./scripts/setup_signing_secrets.sh                 # erzeugt Keystore + setzt 4 Secrets
#   ./scripts/setup_signing_secrets.sh --keystore ~/mein.p12 --alias kaoss
#   ./scripts/setup_signing_secrets.sh --print-base64  # nur Base64 fuer die Web-UI ausgeben
#
# Ergebnis: .github/workflows/android-signed-apk.yml signiert ab dem naechsten
# Build mit immer demselben Zertifikat (SIGNING_IDENTITY=repo-secret). Dadurch
# sind APK-Updates ueber eine bestehende Installation moeglich.
#
# Sicherheit: Der Private Key wird NIE committet. Er liegt unter
# ${KAOSS_SIGNING_DIR:-$HOME/.kaoss-signing} bzw. im GitHub-Secret-Vault.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

SIGNING_DIR="${KAOSS_SIGNING_DIR:-${HOME}/.kaoss-signing}"
KEYSTORE=""
ALIAS="kaoss"
PASSWORD=""
REPO=""
DAYS=3650
LEGACY=0
PRINT_BASE64=0
DRY_RUN=0
DN="/CN=Kaoss Beatbox Studio/OU=Offline CI Release/O=Kaoss/L=Berlin/ST=Berlin/C=DE"

usage() {
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --keystore)   KEYSTORE="${2:?}"; shift 2 ;;
    --alias)      ALIAS="${2:?}"; shift 2 ;;
    --password)   PASSWORD="${2:?}"; shift 2 ;;
    --repo)       REPO="${2:?}"; shift 2 ;;
    --days)       DAYS="${2:?}"; shift 2 ;;
    --legacy)     LEGACY=1; shift ;;
    --print-base64) PRINT_BASE64=1; shift ;;
    --dry-run)    DRY_RUN=1; shift ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "unbekannte Option: $1" >&2; usage; exit 2 ;;
  esac
done

need() { command -v "$1" > /dev/null 2>&1 || { echo "fehlt: $1" >&2; exit 1; }; }
need openssl
need base64

if [ -z "${REPO}" ]; then
  REPO="$(git remote get-url origin 2>/dev/null | sed -E 's#.*github.com[:/]##; s#\.git$##')"
fi
[ -n "${REPO}" ] || { echo "kein Repo erkannt, --repo owner/name setzen" >&2; exit 1; }

umask 077
mkdir -p "${SIGNING_DIR}"

if [ -z "${KEYSTORE}" ]; then
  KEYSTORE="${SIGNING_DIR}/kaoss-release.p12"
fi

# --------------------------------------------------------------------------- #
# 1. Keystore: vorhanden nutzen oder neu erzeugen (PKCS12, RSA-2048, 10 Jahre)
# --------------------------------------------------------------------------- #
if [ ! -f "${KEYSTORE}" ]; then
  if [ -z "${PASSWORD}" ]; then PASSWORD="$(openssl rand -hex 24)"; fi
  KEY_PEM="${KEYSTORE%.p12}-key.pem"
  CERT_PEM="${KEYSTORE%.p12}-cert.pem"
  echo ">> erzeugen: ${KEYSTORE} (RSA-2048, ${DAYS} Tage, alias=${ALIAS})"
  if [ "${DRY_RUN}" = 1 ]; then
    echo "   (dry-run: keine Dateien geschrieben)"
  else
    openssl req -x509 -newkey rsa:2048 -sha256 -days "${DAYS}" -nodes \
      -keyout "${KEY_PEM}" -out "${CERT_PEM}" -subj "${DN}" \
      -addext "basicConstraints=critical,CA:FALSE" \
      -addext "keyUsage=critical,digitalSignature" \
      -addext "extendedKeyUsage=codeSigning" 2>/dev/null
    if [ "${LEGACY}" = 1 ]; then
      # Fuer sehr alte JDKs: 3DES/SHA1 statt AES-256.
      openssl pkcs12 -export -inkey "${KEY_PEM}" -in "${CERT_PEM}" -name "${ALIAS}" \
        -keypbe PBE-SHA1-3DES -certpbe PBE-SHA1-3DES -macalg SHA1 \
        -out "${KEYSTORE}" -passout "pass:${PASSWORD}"
    else
      openssl pkcs12 -export -inkey "${KEY_PEM}" -in "${CERT_PEM}" -name "${ALIAS}" \
        -out "${KEYSTORE}" -passout "pass:${PASSWORD}"
    fi
    printf 'STORE_PASS=%s\nKEY_PASS=%s\nALIAS=%s\n' "${PASSWORD}" "${PASSWORD}" "${ALIAS}" > "${KEYSTORE}.env"
    chmod 600 "${KEYSTORE}" "${KEYSTORE}.env" "${KEY_PEM}" "${CERT_PEM}"
  fi
else
  echo ">> vorhanden: ${KEYSTORE}"
  if [ -z "${PASSWORD}" ]; then
    if [ -f "${KEYSTORE}.env" ]; then
      # shellcheck disable=SC1090
      . "${KEYSTORE}.env"
      PASSWORD="${STORE_PASS:-${PASSWORD}}"
      ALIAS="${ALIAS:-kaoss}"
    else
      echo "   --password wird benoetigt (kein ${KEYSTORE}.env gefunden)" >&2
      exit 1
    fi
  fi
fi

# --------------------------------------------------------------------------- #
# 2. Base64 + oeffentliches Zertifikat
# --------------------------------------------------------------------------- #
BASE64_FILE="${KEYSTORE}.base64"
if [ "${DRY_RUN}" != 1 ] && [ -f "${KEYSTORE}" ]; then
  base64 -w0 "${KEYSTORE}" > "${BASE64_FILE}" 2>/dev/null || base64 "${KEYSTORE}" | tr -d '\n' > "${BASE64_FILE}"
  chmod 600 "${BASE64_FILE}"
  CERT_OUT="$(mktemp)"
  openssl pkcs12 -in "${KEYSTORE}" -nokeys -clcerts -passin "pass:${PASSWORD}" -out "${CERT_OUT}" 2>/dev/null || true
  if grep -q "BEGIN CERTIFICATE" "${CERT_OUT}" 2>/dev/null; then
    mkdir -p android/signing
    cp "${CERT_OUT}" android/signing/kaoss-ci-release-cert.pem
    openssl x509 -in "${CERT_OUT}" -noout -fingerprint -sha256 -subject -dates \
      > android/signing/kaoss-ci-release-fingerprint.txt
    echo ">> oeffentliches Zertifikat: android/signing/kaoss-ci-release-cert.pem"
    cat android/signing/kaoss-ci-release-fingerprint.txt
  fi
  rm -f "${CERT_OUT}"
fi

if [ "${PRINT_BASE64}" = 1 ]; then
  echo ">> Base64 fuer Settings -> Secrets and variables -> Actions (KAOSS_KEYSTORE_BASE64):"
  cat "${BASE64_FILE}"
  echo ""
  echo ">> KAOSS_KEYSTORE_PASSWORD / KAOSS_KEY_PASSWORD: ${PASSWORD}"
  echo ">> KAOSS_KEY_ALIAS: ${ALIAS}"
  exit 0
fi

# --------------------------------------------------------------------------- #
# 3. Secrets setzen (benoetigt gh mit admin:repo)
# --------------------------------------------------------------------------- #
if [ "${DRY_RUN}" = 1 ]; then
  echo ">> dry-run: wuerde 4 Secrets in ${REPO} setzen"
  exit 0
fi

need gh
echo ">> Secrets setzen in ${REPO}"
base64 -w0 "${KEYSTORE}" 2>/dev/null | gh secret set KAOSS_KEYSTORE_BASE64 --repo "${REPO}" \
  || base64 "${KEYSTORE}" | tr -d '\n' | gh secret set KAOSS_KEYSTORE_BASE64 --repo "${REPO}"
printf '%s' "${PASSWORD}" | gh secret set KAOSS_KEYSTORE_PASSWORD --repo "${REPO}"
printf '%s' "${ALIAS}"     | gh secret set KAOSS_KEY_ALIAS --repo "${REPO}"
printf '%s' "${PASSWORD}" | gh secret set KAOSS_KEY_PASSWORD --repo "${REPO}"

echo ""
echo "Fertig. Naechste Schritte:"
echo "  1. git add android/signing/kaoss-ci-release-cert.pem android/signing/kaoss-ci-release-fingerprint.txt"
echo "     git commit -m 'chore(signing): oeffentliches CI-Release-Zertifikat'   (nur Public-Teil!)"
echo "  2. gh workflow run 'Android signed APK (CI/CD + GitHub Release)' --repo ${REPO} --ref $(git rev-parse --abbrev-ref HEAD)"
echo "  3. gh release download apk-latest --repo ${REPO} --pattern '*.apk' --clobber"
echo ""
echo "Keystore-Backup (sicher verwahren, nie ins Repo): ${KEYSTORE}"
