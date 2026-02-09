# Harbor: Создание ЦА и подписание сертификата

Для обеспечения доверия хостов к репозиторию Harbor необходимо создать Центр Сертификации (CA) и выпустить подписанные сертификаты.

Создаём директорию для хранения сертификатов:
```bash
sudo mkdir -p ~/harbor/certs
cd ~/harbor/certs
```
Создаём сертификаты корневого ЦА:
```bash
# Root CA key
openssl genrsa -out root-ca.key 4096

# Root CA cert (на 10 лет, можно меньше)
openssl req -x509 -new -nodes -sha256 -days 3650 
  -key root-ca.key -out root-ca.crt 
  -subj "/C=RU/ST=Moscow/L=Moscow/O=HomeLab/OU=ITZM/CN=My-Root-CA"
```
Измените значения переменных на ваше имя и IP Harbor сервера:
```bash
export HARBOR_HOST=harbor.example.local
export MyIP=2.2.2.2
```
Выполните команды для создания серверных сертификатов Harbor:
```bash
# server key
openssl genrsa -out ${HARBOR_HOST}.key 4096

# csr config with SAN
cat > ${HARBOR_HOST}.csr.cnf <<EOF
[req]
default_bits       = 4096
prompt             = no
default_md         = sha256
distinguished_name = dn
req_extensions     = req_ext

[dn]
C=RU
ST=Moscow
L=Moscow
O=HomeLab
OU=ITZM
CN=${HARBOR_HOST}

[req_ext]
subjectAltName = @alt_names

[alt_names]
DNS.1 = ${HARBOR_HOST}
IP.1  = ${MyIP}
EOF

# create CSR
openssl req -new -key ${HARBOR_HOST}.key -out ${HARBOR_HOST}.csr -config ${HARBOR_HOST}.csr.cnf

# sign server cert by our CA
openssl x509 -req -in ${HARBOR_HOST}.csr -CA root-ca.crt -CAkey root-ca.key -CAcreateserial 
  -out ${HARBOR_HOST}.crt -days 825 -sha256 
  -extensions req_ext -extfile ${HARBOR_HOST}.csr.cnf
```
В результате будут созданы:
*   `root-ca.crt` - корневой сертификат, который необходимо распространить на все клиентские хосты.
*   `${HARBOR_HOST}.crt` и `${HARBOR_HOST}.key` - серверные сертификаты для Harbor.

## Распространение корневого CA сертификата
Скопируйте `root-ca.crt` на все хосты, которые будут взаимодействовать с Harbor.

Для **Ubuntu**:
```bash
sudo cp root-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```
Для **CentOS**:
```bash
sudo cp root-ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust extract
```
После установки сертификатов перезапустите Docker на хостах:
```bash
systemctl restart docker.service
```
