"""
Generate self-signed SSL certificate for Voice Bridge

支持生成两种格式：
- server.crt / server.key: 用于 uvicorn 服务端
- VoiceBridge.p12: 用于手机端一键安装（免密码）
"""
import ssl
import datetime
import os

# Try to use cryptography library
try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    USE_CRYPTOGRAPHY = True
    print("Using cryptography library to generate certificate")
except ImportError:
    USE_CRYPTOGRAPHY = False
    print("cryptography not available, trying ssl module")


def get_local_ip():
    """Get local LAN IP address"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "192.168.1.100"


def generate_cert_openssl(cert_dir, domains):
    """Generate certificate using openssl command"""
    import subprocess
    import ipaddress
    
    key_file = os.path.join(cert_dir, "server.key")
    cert_file = os.path.join(cert_dir, "server.crt")
    
    # Build SAN - 正确区分 IP 地址和域名
    san_parts = []
    for d in domains:
        try:
            ipaddress.ip_address(d)
            san_parts.append(f"IP:{d}")  # 是 IP 地址
        except ValueError:
            san_parts.append(f"DNS:{d}")  # 是域名
    alt_names = ",".join(san_parts)
    
    # 用第一个域名（非IP）作为 CN
    cn = next((d for d in domains if not d.replace('.','').isdigit()), domains[0])
    
    config_content = f"""
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req
req_extensions = v3_req

[dn]
C = CN
ST = BJ
L = Beijing
O = VoiceBridge
CN = {cn}

[v3_req]
subjectAltName = {alt_names}
basicConstraints = CA:FALSE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
"""
    
    config_file = os.path.join(cert_dir, "openssl.cnf")
    with open(config_file, "w") as f:
        f.write(config_content)
    
    # 生成私钥
    subprocess.run([
        "openssl", "genrsa", "-out", key_file, "2048"
    ], check=True, capture_output=True)
    
    # 生成证书
    subprocess.run([
        "openssl", "req", "-x509", "-new", "-nodes",
        "-key", key_file,
        "-out", cert_file,
        "-days", "365",
        "-config", config_file
    ], check=True, capture_output=True)
    
    # 生成 PKCS12 格式（手机一键安装，无需密码）
    p12_file = os.path.join(cert_dir, "VoiceBridge.p12")
    try:
        subprocess.run([
            "openssl", "pkcs12", "-export",
            "-in", cert_file,
            "-inkey", key_file,
            "-out", p12_file,
            "-name", "VoiceBridge",
            "-passout", "pass:"  # 无密码，方便一键安装
        ], check=True, capture_output=True)
        print(f"Mobile install package: {p12_file}")
    except Exception as e:
        print(f"PKCS12 generation skipped: {e}")
    
    print(f"Certificate generated: {cert_file}")
    print(f"Private key generated: {key_file}")
    return cert_file, key_file


def generate_cert_cryptography(cert_dir, domains):
    """Generate certificate using cryptography library"""
    import ipaddress
    
    key_file = os.path.join(cert_dir, "server.key")
    cert_file = os.path.join(cert_dir, "server.crt")
    p12_file = os.path.join(cert_dir, "VoiceBridge.p12")
    
    # 生成 RSA 私钥
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    
    # 构建证书
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Beijing"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Beijing"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "VoiceBridge"),
        x509.NameAttribute(NameOID.COMMON_NAME, domains[0]),
    ])
    
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(d) if not d.replace('.', '').isdigit() else x509.IPAddress(
                    ipaddress.ip_address(d)
                )
                for d in domains
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256(), default_backend())
    )
    
    # 保存 PEM 格式（服务端用）
    with open(key_file, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
    
    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    
    # 生成 PKCS12 格式（手机一键安装，无需密码）
    try:
        from cryptography.hazmat.primitives.serialization import pkcs12
        p12_bytes = pkcs12.serialize_key_and_certificates(
            name=b"VoiceBridge",
            key=key,
            cert=cert,
            cas=None,
            encryption_algorithm=serialization.BestAvailableEncryption(b"")  # 无密码
        )
        with open(p12_file, "wb") as f:
            f.write(p12_bytes)
        print(f"Mobile install package: {p12_file}")
    except Exception as e:
        print(f"PKCS12 generation skipped: {e}")
    
    print(f"Certificate generated: {cert_file}")
    print(f"Private key generated: {key_file}")
    return cert_file, key_file


def main():
    cert_dir = os.path.dirname(os.path.abspath(__file__)) or "."
    cert_dir = os.path.join(cert_dir, "certs")
    os.makedirs(cert_dir, exist_ok=True)
    
    local_ip = get_local_ip()
    
    domains = [
        "localhost",
        "127.0.0.1",
        local_ip,
    ]
    
    print(f"\n[*] Will generate certificate for:")
    for d in domains:
        print(f"   - {d}")
    print()
    
    if USE_CRYPTOGRAPHY:
        try:
            cert_file, key_file = generate_cert_cryptography(cert_dir, domains)
            print("\n[*] Certificate generated successfully!")
            return cert_file, key_file
        except Exception as e:
            print(f"cryptography failed: {e}")
    
    try:
        cert_file, key_file = generate_cert_openssl(cert_dir, domains)
        print("\n[*] Certificate generated successfully!")
        return cert_file, key_file
    except Exception as e:
        print(f"openssl command failed: {e}")
        print("\n[*] Cannot generate certificate. Please install OpenSSL or cryptography:")
        print("   pip install cryptography")
        return None, None


if __name__ == "__main__":
    cert, key = main()
    if cert and key:
        print(f"\n[*] Usage:")
        print(f"   Server cert: {cert}")
        print(f"   Server key: {key}")
        print(f"\n[*] For mobile installation:")
        print(f"   Download VoiceBridge.p12 from /setup/cert-p12")
