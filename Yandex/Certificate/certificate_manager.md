# Yandex Certificate Manager: Выпуск TLS-сертификатов

## 1. Определения

**Certificate Manager** — сервис Yandex Cloud для выпуска, хранения и автоматического продления TLS-сертификатов. Поддерживает сертификаты от Let's Encrypt и собственные (самоподписанные) сертификаты.

**Managed Certificate** — сертификфикат, который Certificate Manager выпускает и автоматически продлевает. Привязывается к Application Load Balancer или CloudFront-ресурсам.

**DNS-валидация** — метод подтверждения владения доменом через DNS-запись (TXT) в зоне DNS. Требует делегированной DNS-зоны.

**HTTP-валидация** — метод подтверждения через HTTP-ответ на определённый путь (`/acme-challenge/`).

---

## 2. Базовые концепции

### Типы сертификатов

| Тип | Описание | Валидация | Срок действия |
| :--- | :--- | :--- | :--- |
| **Let's Encrypt** | Бесплатные сертификаты с автоматическим продлением | DNS-01 или HTTP-01 | 90 дней (автопродление) |
| **Самоподписанные** | Сертификаты, выпущенные внутри YC | Автоматически | До 2 лет |

### Методы валидации

- **DNS-01** — создание TXT-записи в DNS-зоне. Требует доступа к зоне.
- **HTTP-01** — размещение файла на сервере по пути `/.well-known/acme-challenge/`.
- **TLS-ALPN-01** — ответ сервера на TLS-соединение с определённым ALPN.

> **Важно:** для выпуска сертификата необходима DNS- или HTTP-валидация. Wildcard-сертификаты (`*.example.com`) требуют DNS-валидации.

---

## 3. Практические сценарии

### Выпуск wildcard-сертификата через Certificate Manager

```bash
# Запросить wildcard-сертификат для домена и субдомена
yc certificate-manager certificate request \
  --name my-wildcard-cert \
  --domains example.com,*.example.com

# Проверить статус выпуска
yc certificate-manager certificate list --format json | \
  jq -r '.[] | "\(.name)\t\(.status)\t\(.not_after)"'
# → my-wildcard-cert<TAB>ISSUED<TAB>2026-12-31T23:59:59Z
```

**DNS-валидация:**
1. После `certificate request` система создаёт DNS-запросы для подтверждения.
2. Делегируйте зону DNS в Yandex DNS или создайте TXT-запись вручную.
3. Статус сертификата меняется на `ISSUED` после подтверждения.

### Привязка сертификата к Application Load Balancer

```bash
# Получить ID сертификата
CERT_ID=$(yc certificate-manager certificate get --name my-wildcard-cert --format json | jq -r '.id')

# Привязать к HTTPS-сlistener ALB
yc application-load-balancer http-router update \
  --name my-router \
  --certificates $CERT_ID
```

### Обновление сертификата

```bash
# Обновить список доменов (создаётся новая ревизия сертификата)
yc certificate-manager certificate update \
  --name my-wildcard-cert \
  --domains example.com,*.example.com,api.example.com
```

---

## 4. Дополнительная информация

- **Автоматическое продление:** сертификаты Let's Encrypt продляются за 30 дней до истечения срока действия.
- **Интеграция с CDN:** сертификаты можно использовать в качестве пользовательских SSL-сертификатов для CDN-зон.
- **Связанные темы:** [VPC](./../VPC.md) — для создания DNS-зон и делегирования, [Load Balancer](./../VPC.md#load-balancer-диагностика-nlb-и-alb) — для привязки сертификатов к ALB.
