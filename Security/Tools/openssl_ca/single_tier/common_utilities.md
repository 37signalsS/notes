# Дополнительная информация и утилиты (одноуровневый CA)

### Практический пример — mTLS в Nginx

Подробное описание и практический пример настройки mTLS в Nginx можно найти в разделе [Аутентификация по клиентским SSL-сертификатам (mTLS)](../../WebServers/Nginx/Security/nginx_tls_ssl_configuration.md#аутентификация-по-клиентским-ssl-сертификатам-mtls)

### Полезные команды для проверки

**Просмотреть содержимое сертификата:**
```bash
openssl x509 -in my-service.crt -noout -text
```

**Просмотреть содержимое CSR:**
```bash
openssl req -in my-service.csr -noout -text
```

**Проверить соответствие ключа и сертификата:**
(Хеши модулей должны совпадать)
```bash
openssl rsa -noout -modulus -in my-service.key | openssl md5
openssl x509 -noout -modulus -in my-service.crt | openssl md5
```

**Просмотреть содержимое CRL:**
```bash
openssl crl -in ca/crl.pem -noout -text
```

**Проверить дату окончания срока действия сертификата:**
```bash
openssl x509 -in my-service.crt -noout -enddate
```

**Подключиться к TLS-серверу и показать его сертификат:**
```bash
# Замените my-service.local:443 на нужный адрес и порт
openssl s_client -connect my-service.local:443 -showcerts < /dev/null
```
