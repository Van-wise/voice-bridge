# -*- coding: utf-8 -*-
"""
Voice Bridge 局域网预置证书生成器

生成 10 年有效期的自签名证书，支持所有常用局域网 IP 段：
- localhost, 127.0.0.1
- 192.168.0.0/16 (家用路由器)
- 10.0.0.0/8 (大公司内网)
- 172.16.0.0/12 (Docker/K8s)

用户无需生成，开箱即用。
"""

import os
import sys
import datetime
import ipaddress

# 检查 cryptography 库
try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID, ExtensionOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
except ImportError:
    print("[ERROR] cryptography library required")
    print("   pip install cryptography")
    sys.exit(1)


def get_local_ip():
    """获取本机局域网 IP"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "192.168.1.100"


def generate_lan_cert(cert_dir: str = None):
    """
    生成局域网通用证书

    Args:
        cert_dir: 证书保存目录，默认在脚本同目录的 certs 文件夹
    """
    if cert_dir is None:
        cert_dir = os.path.join(os.path.dirname(__file__), "certs")

    os.makedirs(cert_dir, exist_ok=True)

    cert_file = os.path.join(cert_dir, "lan_cert.pem")
    key_file = os.path.join(cert_dir, "lan_key.pem")

    # 如果证书已存在，跳过生成
    if os.path.exists(cert_file) and os.path.exists(key_file):
        print("[OK] Certificate already exists: " + cert_file)
        return cert_file, key_file

    print("=" * 50)
    print(" Voice Bridge LAN Certificate Generator")
    print("=" * 50)
    print(" Valid for: 10 years (3650 days)")
    print(" Save to: " + cert_dir)
    print("")

    # 生成 RSA 私钥
    print("[1/3] Generating RSA private key (2048 bit)...")
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    # 证书信息
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Beijing"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Beijing"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "VoiceBridge"),
        x509.NameAttribute(NameOID.COMMON_NAME, "VoiceBridge LAN"),
    ])

    # 计算有效期（10年）- 使用 timezone-aware datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    valid_from = now
    valid_to = now + datetime.timedelta(days=3650)

    local_ip = get_local_ip()

    # 构建 SAN（Subject Alternative Name）
    print("[2/3] Building certificate with SAN...")
    san_names = [
        # 本地地址
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
        x509.DNSName("localhost"),
        x509.DNSName("localhost.localdomain"),
        # 当前局域网 IP
        x509.IPAddress(ipaddress.IPv4Address(local_ip)),
        # 常用局域网段 - 添加具体 IP
        x509.IPAddress(ipaddress.IPv4Address("192.168.0.1")),
        x509.IPAddress(ipaddress.IPv4Address("192.168.1.1")),
        x509.IPAddress(ipaddress.IPv4Address("192.168.31.1")),
        x509.IPAddress(ipaddress.IPv4Address("192.168.50.1")),
        x509.IPAddress(ipaddress.IPv4Address("192.168.100.1")),
        x509.IPAddress(ipaddress.IPv4Address("10.0.0.1")),
        x509.IPAddress(ipaddress.IPv4Address("10.0.1.1")),
        x509.IPAddress(ipaddress.IPv4Address("10.10.1.1")),
        x509.IPAddress(ipaddress.IPv4Address("172.16.0.1")),
        x509.IPAddress(ipaddress.IPv4Address("172.17.0.1")),
        x509.IPAddress(ipaddress.IPv4Address("172.31.0.1")),
    ]

    # 构建证书
    print("[3/3] Signing certificate...")
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(valid_to)
        .add_extension(
            x509.SubjectAlternativeName(san_names),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
                x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
            ]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256(), default_backend())
    )

    # 保存私钥
    print("   Saving private key...")
    with open(key_file, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))

    # 保存证书
    print("   Saving certificate...")
    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print("")
    print("=" * 50)
    print(" [SUCCESS] Certificate generated!")
    print("=" * 50)
    print(" Certificate: " + cert_file)
    print(" Private Key: " + key_file)
    print(" Valid: " + valid_from.strftime("%Y-%m-%d") + " ~ " + valid_to.strftime("%Y-%m-%d"))
    print("")
    print(" Access URLs:")
    print("   - https://localhost:8080")
    print("   - https://127.0.0.1:8080")
    print("   - https://" + local_ip + ":8080")
    print("")
    print(" First-time mobile access:")
    print("   1. Browser shows security warning")
    print("   2. Click [Advanced] -> [Continue]")
    print("   3. Only need 1 click, auto-trust after")
    print("=" * 50)

    return cert_file, key_file


if __name__ == "__main__":
    generate_lan_cert()
