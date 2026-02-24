# Дополнительная информация и утилиты

### Пример: mTLS в Nginx

Подробное описание и практический пример настройки mTLS в Nginx можно найти в разделе [Аутентификация по клиентским SSL-сертификатам (mTLS)](../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md#аутентификация-по-клиентским-ssl-сертификатам-mtls).

### Полезные команды

- **Просмотреть содержимое сертификата:**
  `openssl x509 -in my-service.crt -noout -text`
- **Просмотреть содержимое CSR:**
  `openssl req -in my-service.csr -noout -text`
- **Просмотреть содержимое CRL:**
  `openssl crl -in intermediate-ca/crl/crl.pem -noout -text`
- **Проверить соответствие ключа и сертификата:** (хеши модулей должны совпадать)

  ```bash
  openssl rsa -noout -modulus -in my-service.key | openssl md5
  openssl x509 -noout -modulus -in my-service.crt | openssl md5
  ```

- **Подключиться к TLS-серверу и показать его сертификат:**
  `openssl s_client -connect my-service.local:443 -showcerts < /dev/null`
- **Проверить цепочку доверия для файла fullchain:**
  `openssl verify -CAfile root-ca/ca.crt my-service.fullchain.crt`
