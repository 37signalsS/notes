# Безопасность VictoriaMetrics (single-node / cluster)

## Определения

**Secure-флаги VM** — набор CLI-флагов, включающих аутентификацию и TLS на HTTP-интерфейсах компонентов (`-httpAuth.username`/`-httpAuth.password`, `-tls`, `-tlsCertFile`, `-tlsKeyFile`, `-tlsMinVersion`).

**mTLS (mutual TLS)** — двусторонняя аутентификация по сертификатам. В кластере VictoriaMetrics доступна в Enterprise-версии между `vminsert`/`vmselect`/`vmstorage` и на `vmauth` к компонентам.

**vmgateway** — Enterprise-компонент, оборачивающий доступ к кластеру поверх `vmauth`/`vmsingle` с поддержкой JWT/OIDC и тенантными ACL.

## Базовые концепции

### Периметр аутентификации в stack

```
внешний мир (Grafana, агенты, curl)
   │  Basic Auth / Bearer / JWT / OIDC
   ▼
┌──────────┐
│  vmauth  │  (доп. vmgateway в Enterprise)
│  vmgateway│
└────┬─────┘
     │ optional mTLS (Enterprise)
     ▼
 vminsert / vmselect / vmsingle / vmalert / vlselect
```

Danger zones: `/metrics`, `/api/v1/write`, `/insert/*`, `/select/*`, `/vmui`. Их никогда нельзя открывать «в мир» без прокси.

### Ключевые флаги защиты

| Компонент | Флаги |
| :--- | :--- |
| vmagent | `-promscrape.config` + `-remoteWrite.url` c `?username&password` или TLS; сам - `-httpAuth.*`, `-tls*` |
| vmsingle | `-httpAuth.username`/`-httpAuth.password`, `-tls`, `-tlsCertFile`, `-tlsKeyFile`, `-tlsMinVersion` |
| vmauth | `-auth.config` (пользователи), `-tls*` на себя |
| vmalert | `-datasource.url` c creds, `-notifier.url`, `-remoteWrite.url` |
| vminsert/vmselect (cluster) | те же `-httpAuth.*`; Enterprise — mTLS (`-tls*` + `-insecureSkipVerify` на партнёрах) |

### Шифрование в покое

- VictoriaMetrics не шифрует данные на диске «из коробки»: для encryption-at-rest используйте LUKS/dm-crypt на уровне ФС или шифрование диска провайдера.
- В Kubernetes — volume encryption (например, PVC-snapshots с шифрованным storageClass).

## Практические сценарии

### 1. Базовая аутентификация vmsingle

```bash
victoria-metrics \
  -storageDataPath=/var/lib/victoria-metrics \
  -httpAuth.username=vm \
  -httpAuth.password=${VM_PASSWORD} \
  -tls -tlsCertFile=/etc/vm/tls.crt -tlsKeyFile=/etc/vm/tls.key \
  -tlsMinVersion=TLS1.2
```

Пароль лучше передавать из файла/секрета, не в командной строке.

### 2. Тенантные ACL через vmauth (основной способ для кластера)

```yaml
users:
  - username: grafana
    password: grafana-secret
    url_prefix: http://vmselect:8481/select/0/prometheus/
  - username: vmagent
    password: write-secret
    url_prefix: http://vminsert:8480/insert/0/prometheus/
```

Подробный формат — [vmauth](./vmauth_overview.md).

### 3. mTLS в кластере (Enterprise)

```bash
# vmstorage с mTLS
vmstorage -httpListenAddr=:8482 -tls -tlsCertFile=... -tlsKeyFile=... \
  -mtls -mtlsCaFile=... -mtlsKeyFile=... /*cert/key для клиентов*/

# vminsert подключается с клиентским сертификатом
vminsert -storageNode=vmstorage-0:8400 ... -tls -tlsCertFile=... -tlsKeyFile=...
```

Точный набор флагов утоняется по версии; см. официальную документацию «Security» для cluster.

## Валидация установки

```bash
# Запрос без пароля должен отклоняться
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8428/metrics
# → 401

# Правильная аутентификация
curl -s -u vm:${VM_PASSWORD} http://localhost:8428/metrics | head

# TLS-руководство: проверка сертификата
echo | openssl s_client -connect localhost:8428 -servername localhost 2>/dev/null | grep subject=
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `401` даже с паролем | Неверный пользователь, спецсимволы в пароле | Проверить значение `-httpAuth.username`, экранирование; для vmauth — порядок `users[]` |
| `400` при use TLS | Сертификат не подписан, неверный формат | Проверить `-tlsCertFile`/`-tlsKeyFile`, цепочку и CN |
| mTLS-провал между компонентами | Разные CA / нет клиентского сертификата | Сверить `-tlsCaFile` и trust store; перевыпустить сертификаты |
| Прямой доступ к /insert возможен извне | Не настроен прокси-периметр | Всюду ставить `vmauth` и закрыть порты firewall-ом |
| `-httpAuth` мешает vmalert | vmalert не передаёт creds | В `-datasource.url` добавить `?username=...&password=...` или настроить заголовки/токен |

## Рекомендации по эксплуатации

- Всегда «прикрывайте» `/insert/*` и `/select/*` прокси (`vmauth`), не выдавайте прямых адресов компонентов наружу.
- Включите TLS везде, где трафик выходит за границы доверенной сети; `-tlsMinVersion=TLS1.2+`.
- Для кластера мTal — Enterprise; в Community закрывайте сеть (network policies, firewalls) изолирующими правилами.
- Ротайте пароли и сертификаты по расписанию; используйте секреты (Vault/k8s secrets), а не переменные окружения в CLI.
- Логируйте и аудитируйте доступ: на уровне `vmauth`/`vmgateway` смотрите обнуляющие попытки авторизации.

## Ограничения и особые случаи

- Basic auth на `-httpAuth.*` — только на HTTP-порту самого компонента, не заменяет TLS outside perimeter.
- mTLS между компонентами кластера — Enterprise-возможность; в Community полагайтесь на сетевую изоляцию.
- `vmgateway` ориентирован на тенантный доступ (JWT), но для полноценного SSO/аудита его часто комбинируют с `vmauth`/OIDC-провайдером.

## Дополнительная информация

### См. также

- [vmauth: прокси и маршрутизация](./vmauth_overview.md) — пользователи, ACL, токены;
- [VictoriaMetrics: обзор](./overview.md) — флаги и сетевые порты;
- [Prometheus: безопасность](../Prometheus/security.md) — аналог для стека Prometheus.
# force reindex test
