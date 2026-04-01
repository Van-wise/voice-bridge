"""重新生成正确的 SSL 证书（修复 SAN IP/DNS 混淆问题）"""
import os
import datetime
import ipaddress
import socket

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa

# 获取本机局域网 IP
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '192.168.1.9'

local_ip = get_local_ip()
print(f'[*] Local IP: {local_ip}')

cert_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'certs')
os.makedirs(cert_dir, exist_ok=True)

# 生成 RSA 私钥
key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
    backend=default_backend()
)

# 构建 SAN - 正确区分 DNS 域名 和 IP 地址
san_entries = [
    x509.DNSName('localhost'),
    x509.IPAddress(ipaddress.ip_address('127.0.0.1')),
    x509.IPAddress(ipaddress.ip_address(local_ip)),
]

subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COUNTRY_NAME, 'CN'),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'VoiceBridge'),
    x509.NameAttribute(NameOID.COMMON_NAME, 'localhost'),
])

now = datetime.datetime.now(datetime.timezone.utc)

cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now)
    .not_valid_after(now + datetime.timedelta(days=3650))  # 10年有效期
    .add_extension(
        x509.SubjectAlternativeName(san_entries),
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
            content_commitment=True,
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
            x509.ExtendedKeyUsageOID.SERVER_AUTH,
            x509.ExtendedKeyUsageOID.CLIENT_AUTH,
        ]),
        critical=False,
    )
    .sign(key, hashes.SHA256(), default_backend())
)

key_file = os.path.join(cert_dir, 'server.key')
cert_file = os.path.join(cert_dir, 'server.crt')

# 写入文件
with open(key_file, 'wb') as f:
    f.write(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    ))

with open(cert_file, 'wb') as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))

# 验证证书内容
print(f'[*] Certificate: {cert_file}')
print(f'[*] Private key: {key_file}')
print(f'[*] Valid for 10 years')

loaded = x509.load_pem_x509_certificate(open(cert_file, 'rb').read())
san = loaded.extensions.get_extension_for_class(x509.SubjectAlternativeName)
dns_names = san.value.get_values_for_type(x509.DNSName)
ip_addrs = [str(ip) for ip in san.value.get_values_for_type(x509.IPAddress)]

print(f'[*] SAN DNS names : {dns_names}')
print(f'[*] SAN IP addrs  : {ip_addrs}')
print()
print('[OK] Certificate generated successfully!')
print()
print('Next steps:')
print('  1. Restart Voice Bridge backend')
print(f'  2. On phone, visit: https://{local_ip}:7266')
print('  3. Accept the certificate warning in browser')
