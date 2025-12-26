#!/bin/bash
# ==============================================================================
# Generate Redis TLS Certificates
# ==============================================================================
# Creates self-signed certificates for Redis TLS encryption
#
# Usage:
#   ./scripts/generate_redis_certs.sh
#
# Output:
#   - certs/ca.crt (CA certificate)
#   - certs/ca.key (CA private key)
#   - certs/redis.crt (Redis server certificate)
#   - certs/redis.key (Redis server private key)
# ==============================================================================

set -e  # Exit on error

CERTS_DIR="./certs"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "===================================================================="
echo "  Redis TLS Certificate Generation"
echo "===================================================================="
echo ""

# Check if openssl is installed
if ! command -v openssl &> /dev/null; then
    echo -e "${RED}❌ Error: openssl is not installed${NC}"
    echo "Install with: brew install openssl (macOS) or apt install openssl (Linux)"
    exit 1
fi

# Create certs directory
if [ -d "$CERTS_DIR" ]; then
    echo -e "${YELLOW}⚠️  Warning: certs/ directory already exists${NC}"
    read -p "Overwrite existing certificates? (yes/no): " OVERWRITE
    if [ "$OVERWRITE" != "yes" ]; then
        echo "Aborted."
        exit 1
    fi
    echo "Backing up existing certs..."
    tar -czf "certs_backup_$(date +%Y%m%d_%H%M%S).tar.gz" "$CERTS_DIR"
    rm -rf "$CERTS_DIR"
fi

mkdir -p "$CERTS_DIR"
chmod 700 "$CERTS_DIR"

echo "Creating certificates directory..."
echo ""

# ============================================================================
# Step 1: Generate Certificate Authority (CA)
# ============================================================================

echo "Step 1: Generating Certificate Authority (CA)..."

openssl genrsa -out "$CERTS_DIR/ca.key" 4096

openssl req -new -x509 -days 3650 -key "$CERTS_DIR/ca.key" -out "$CERTS_DIR/ca.crt" \
    -subj "/C=US/ST=State/L=City/O=SLOB Trading/OU=IT/CN=SLOB CA"

echo -e "${GREEN}✅ CA certificate generated${NC}"
echo ""

# ============================================================================
# Step 2: Generate Redis Server Certificate
# ============================================================================

echo "Step 2: Generating Redis server certificate..."

# Generate private key
openssl genrsa -out "$CERTS_DIR/redis.key" 4096

# Generate certificate signing request (CSR)
openssl req -new -key "$CERTS_DIR/redis.key" -out "$CERTS_DIR/redis.csr" \
    -subj "/C=US/ST=State/L=City/O=SLOB Trading/OU=IT/CN=redis"

# Create extensions file for SAN (Subject Alternative Names)
cat > "$CERTS_DIR/redis.ext" << EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = redis
DNS.2 = localhost
DNS.3 = 127.0.0.1
IP.1 = 127.0.0.1
EOF

# Sign the certificate with CA
openssl x509 -req -in "$CERTS_DIR/redis.csr" -CA "$CERTS_DIR/ca.crt" -CAkey "$CERTS_DIR/ca.key" \
    -CAcreateserial -out "$CERTS_DIR/redis.crt" -days 3650 -sha256 \
    -extfile "$CERTS_DIR/redis.ext"

# Clean up temporary files
rm "$CERTS_DIR/redis.csr" "$CERTS_DIR/redis.ext" "$CERTS_DIR/ca.srl"

echo -e "${GREEN}✅ Redis server certificate generated${NC}"
echo ""

# ============================================================================
# Step 3: Set Permissions
# ============================================================================

echo "Step 3: Setting file permissions..."

chmod 600 "$CERTS_DIR/ca.key"
chmod 644 "$CERTS_DIR/ca.crt"
chmod 600 "$CERTS_DIR/redis.key"
chmod 644 "$CERTS_DIR/redis.crt"

echo -e "${GREEN}✅ Permissions set:${NC}"
echo "  - Private keys (.key): 600 (rw-------)"
echo "  - Certificates (.crt): 644 (rw-r--r--)"
echo ""

# ============================================================================
# Step 4: Validation
# ============================================================================

echo "Step 4: Validating certificates..."

# Verify certificate
if openssl verify -CAfile "$CERTS_DIR/ca.crt" "$CERTS_DIR/redis.crt" &> /dev/null; then
    echo -e "${GREEN}✅ Certificate verification successful${NC}"
else
    echo -e "${RED}❌ Certificate verification failed${NC}"
    exit 1
fi

# Display certificate info
echo ""
echo "Certificate Information:"
openssl x509 -in "$CERTS_DIR/redis.crt" -noout -subject -issuer -dates

echo ""
echo "===================================================================="
echo "  Summary"
echo "===================================================================="
echo ""
echo "Certificates created:"
ls -lh "$CERTS_DIR"

echo ""
echo -e "${GREEN}✅ Redis TLS certificates generated successfully!${NC}"
echo ""
echo "Next steps:"
echo "  1. Update docker-compose.yml to mount certificates"
echo "  2. Configure Redis to use TLS"
echo "  3. Update SLOB application Redis connection to use TLS"
echo "  4. Test Redis TLS connection:"
echo "     redis-cli --tls --cert certs/redis.crt --key certs/redis.key --cacert certs/ca.crt -p 6379 PING"
echo ""
echo -e "${YELLOW}⚠️  SECURITY REMINDERS:${NC}"
echo "  - Keep ca.key and redis.key secure (600 permissions)"
echo "  - NEVER commit private keys to version control"
echo "  - Certificates expire in 10 years (3650 days)"
echo "  - Regenerate certificates before expiration"
echo ""
echo "===================================================================="
