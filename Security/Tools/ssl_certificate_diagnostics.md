# Диагностика SSL/TLS сертификатов

## Определения

**Цепочка доверия (Chain of Trust)** — путь от серверного сертификата к корневому CA через промежуточные сертификаты. Клиент проверяет подпись на каждом уровне цепочки.

**Incomplete chain** — ситуация, когда сервер не отдаёт промежуточные сертификаты, из-за чего клиент не может построить цепочку до доверенного корневого CA.

**CA-хранилище** — набор доверенных корневых и промежуточных сертификатов в ОС. Обновляется пакетом `ca-certificates`.

## Основные концепции

### Проверка даты окончания сертификата

```bash
# Проверить дату окончания сертификата удалённого сервера
echo | openssl s_client -connect example.com:443 \
  -servername example.com 2>/dev/null | \
  openssl x509 -noout -enddate
# notAfter=May 14 18:57:50 2026 GMT
```

**Важно:** Сравните полученную дату с системным временем. Неверное время на сервере может приводить к ложным ошибкам «Certificate Expired».

### Проверка сертификата на ошибки верификации

```bash
openssl s_client -connect example.com:443 \
  </dev/null | \
  grep Verification
```

**Результат без ошибки:**

```
Verification: OK
```

**Результат с ошибкой:**

```
Verification error: unable to verify the first certificate
```

### Типичные ошибки и причины

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `unable to verify the first certificate` | Сервер не отдаёт промежуточные сертификаты | Настроить `ssl_certificate fullchain.crt` на сервере |
| `unable to get local issuer certificate` | На клиенте нет нужного CA в хранилище | Обновить `ca-certificates` или установить промежуточный/корневой вручную |
| `Certificate expired` | Истёк срок действия | Перевыпустить сертификат |
| `Hostname mismatch` | CN/SAN не совпадает с доменом | Выпустить сертификат с правильным SAN |

## Практические сценарии

### Сценарий 1: «unable to verify the first certificate» — неправильная конфигурация сервера

Ошибка означает, что нет доверия ко всей цепочке сертификатов. Самая частая причина — сервер настроен отдавать только сертификат домена, без промежуточных.

**Неправильно (Nginx):**

```nginx
ssl_certificate     /path/example.com.cer;      # только сертификат домена
ssl_certificate_key /path/example.com.key;
```

**Правильно (Nginx):**

```nginx
ssl_certificate     /path/fullchain.cer;         # домен + промежуточные CA
ssl_certificate_key /path/example.com.key;
```

Файл `fullchain` должен содержать сертификат сервера и все промежуточные CA. Подробнее о форматах цепочки: [PKI Overview](../../Concepts/pki_overview.md#форматы-файлов-цепочки).

### Сценарий 2: Устаревшее CA-хранилище на клиенте

Если сервер настроен корректно, но клиент всё равно выдаёт ошибку верификации — проблема в устаревшем CA-хранилище.

**Пример:** Ubuntu 18.04 не может проверить сертификат сайта, выпущенный промежуточным CA 2020 года.

```bash
openssl s_client -connect npchk.nalog.ru:443 </dev/null | grep Verification
# Verification error: unable to verify the first certificate
```

**Решение — обновить CA-хранилище:**

```bash
apt install ca-certificates
```

Если система слишком старая и обновление не помогает — необходимо вручную скачать промежуточный и корневой сертификаты.

### Сценарий 3: Ручная установка промежуточного и корневого сертификатов

Когда CA-хранилище не содержит нужный корневой CA, его нужно добавить вручную.

#### Шаг 1: Получить ссылку на промежуточный сертификат

Ссылка находится в расширении **Authority Information Access (AIA)** сертификата:

```bash
openssl s_client -connect npchk.nalog.ru:443 </dev/null | \
  openssl x509 -noout -text | \
  grep "CA Issuers"
# CA Issuers - URI:http://secure.globalsign.com/cacert/gsgccr3dvtlsca2020.crt
```

#### Шаг 2: Скачать и преобразовать промежуточный сертификат

```bash
# Скачать (может быть в формате DER)
wget http://secure.globalsign.com/cacert/gsgccr3dvtlsca2020.crt \
  -O globalsign-intermediate.crt

# Преобразовать DER → PEM (если нужно)
openssl x509 -inform DER -in globalsign-intermediate.crt \
  -out globalsign-intermediate.pem
```

#### Шаг 3: Определить издателя промежуточного сертификата

```bash
openssl x509 -in globalsign-intermediate.pem -noout -issuer
# issuer=OU = GlobalSign Root CA - R3, O = GlobalSign, CN = GlobalSign
```

#### Шаг 4: Скачать корневой сертификат

Для известных CA (GlobalSign, DigiCert, Let's Encrypt) корневые сертификаты доступны на официальных сайтах:

```bash
wget https://secure.globalsign.net/cacert/Root-R3.crt \
  -O globalsign-root.crt
openssl x509 -inform DER -in globalsign-root.crt \
  -out globalsign-root.pem
```

#### Шаг 5: Проверить цепочку

```bash
openssl verify -CAfile globalsign-root.pem globalsign-intermediate.pem
# globalsign-intermediate.pem: OK
```

#### Шаг 6: Установить в CA-хранилище

```bash
# Скопировать в директорию доверенных сертификатов
# Формат файла должен быть PEM, расширение — обязательно .crt
cp globalsign-root.pem /usr/local/share/ca-certificates/globalsign-root.crt
cp globalsign-intermediate.pem /usr/local/share/ca-certificates/globalsign-intermediate.crt

# Обновить хранилище
update-ca-certificates --fresh
```

#### Шаг 7: Проверить результат

```bash
openssl s_client -connect npchk.nalog.ru:443 </dev/null | grep Verification
# depth=2 OU = GlobalSign Root CA - R3, O = GlobalSign, CN = GlobalSign
# verify return:1
# depth=1 C = BE, O = GlobalSign nv-sa, CN = GlobalSign GCC R3 DV TLS CA 2020
# verify return:1
# depth=0 CN = *.nalog.ru
# verify return:1
# Verification: OK
```

## Дополнительная информация

### Связанные темы

- **[PKI Overview](../../Concepts/pki_overview.md)** — иерархия CA, цепочка доверия, форматы файлов
- **[TLS Protocol](../../../Networking/Protocols/tls.md)** — протокол TLS, рукопожатие, шифры
- **[Nginx TLS Trouleshooting](../../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md)** — диагностика TLS в Nginx
- **[Let's Encrypt / acme.sh](../../../WebServers/Concepts/acme_sh.md)** — автоматический выпуск сертификатов

### Полезные команды

```bash
# Проверить дату окончания локального файла сертификата
openssl x509 -in server.crt -noout -enddate

# Просмотреть содержимое сертификата
openssl x509 -in server.crt -noout -text

# Показать все сертификаты сервера (включая промежуточные)
openssl s_client -connect example.com:443 -showcerts </dev/null

# Проверить цепочку локальных файлов
openssl verify -CAfile ca-bundle.crt server.crt
```
