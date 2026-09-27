# TLS Options, mTLS и сертификаты в Traefik

## Определения

**TLS Options** — набор параметров TLS-хендшейка (минимальная версия протокола, cipher suites, кривые, SNI-политика, клиентская аутентификация), определяемый в динамической конфигурации под именем и привязываемый к роутерам.

**TLSStore** — хранилище сертификатов Traefik; позволяет задать дефолтный (default) сертификат.

**TLS termination** — завершение TLS-соединения на Traefik: TLS снимается, к бэкенду трафик идет в открытом виде.

**TLS passthrough** — «прозрачная» передача зашифрованного потока без прерывания рукопожатия (доступно на TCP-роутерах).

**clientAuth (mTLS)** — требование и проверка клиентского сертификата (взаимная TLS-аутентификация).

## Базовые концепции

### Чем управляют TLS Options

Как и в традиционных веб-серверах, TLS Options позволяют централизованно задать политику безопасности шифрования:

| Поле | Назначение | Значения |
| :--- | :--- | :--- |
| `minVersion` | Минимальная версия TLS | `VersionTLS10`…`VersionTLS13` (Go-имена) |
| `maxVersion` | Максимальная версия TLS | то же; обычно не задают, чтобы не отключать TLS 1.3 |
| `cipherSuites` | Список cipher suites (Go-имена) | `TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256` и т.д. |
| `curvePreferences` | Эллиптические кривые | `CurveP521`, `CurveP384` (или `secp521r1`) |
| `sniStrict` | Строгая проверка SNI: отклонять соединения без `server_name` или с недоверенным именем | `true`/`false` |
| `alpnProtocols` | Согласование ALPN | по умолчанию `h2, http/1.1, acme-tls/1` |
| `disableSessionTickets` | Отключение session tickets | `true`/`false` |
| `clientAuth.caFiles` | CA для проверки клиентских сертификатов | пути к PEM-файлам |
| `clientAuth.clientAuthType` | Режим проверки клиентского сертификата | `NoClientCert`, `RequestClientCert`, `RequireAnyClientCert`, `VerifyClientCertIfGiven`, `RequireAndVerifyClientCert` |

Особенности v3:

- Cipher suites **TLS 1.3 не настраиваются** (они фиксированы протоколом).
- Опция `preferServerCipherSuites` в v3 **удалена**.
- Опции не поддерживаются label/tag-провайдерами (Docker): определить их можно только в File-провайдере или через CRD в Kubernetes, а в Docker-метках — только сослаться на них (`...tls.options=myoptions@file`).

### Как options привязываются к роутерам

Options применяются к **именам (SNI/домены)**, которые фигурируют в правиле роутера, а не к роутеру как таковому. Если два роутера задают противоречащие options для одного хоста — обе привязки отбрасываются, хост откатывается на `default`; при `core.strictTLSOptions: true` роутер вовсе падает (fail closed).

Конфликт Host header и SNI при включённом SNI-роутинге дает `421 Misdirected Request`.

### TLS на TCP-роутерах

TCP-роутеры с `tls` по умолчанию **завершают** TLS. Для передачи трафика «в зашифрованном виде» (например, PostgreSQL с собственным сертификатом) задается `tls.passthrough: true`.

```yaml
tcp:
  routers:
    db-tls:
      rule: "HostSNI(`db.example.com`)"
      service: postgres-tls
      tls:
        passthrough: true
```

В отличие от HTTP, несколько TCP-роутеров могут обслуживать один и тот же `HostSNI` с разными TLS Options (мультиплексор выбирает роут до хендшейка).

### TLS между Traefik и бэкендом

Транспорт «вверх по течению» (toward backend) настраивается через `serversTransport` на HTTP-сервисах: проверка сертификата бэкенда (`rootCAs`), клиентский сертификат для mTLS к бэкенду (`certificates`), `serverName`, `insecureSkipVerify`, version constraints. Для TCP/прозрачности используется TCP ServersTransport (включая `proxyProtocol` при отправке к бэкенду) — см. [Протоколы и потоки данных](./traefik-protocols-advanced.md).

## Практические сценарии

### Сценарий 1: Базовое ужесточение TLS (все роутеры)

Dynamic config (file provider):

```yaml
tls:
  options:
    default:
      minVersion: VersionTLS12
      curvePreferences:
        - CurveP521
        - CurveP384
      cipherSuites:
        - TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256
        - TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384

http:
  routers:
    secure-app:
      rule: "Host(`app.example.com`)"
      service: app-service
      entryPoints: [websecure]
      tls:
        options: default
```

Можно переопределить policy на уровне entrypoint (применяется, пока роутер не задал свою):

```yaml
entryPoints:
  websecure:
    address: ":443"
    http:
      tls:
        options: default
```

### Сценарий 2: Современный профиль и строгий SNI

```yaml
tls:
  options:
    modern:
      minVersion: VersionTLS13
      sniStrict: true
```

### Сценарий 3: mTLS (клиентские сертификаты)

Проверка сертификатов клиентов с пересылкой данных о них в бэкенд:

```yaml
tls:
  options:
    mtls-mandatory:
      minVersion: VersionTLS12
      clientAuth:
        caFiles:
          - /etc/traefik/certs/client-ca.crt
        clientAuthType: RequireAndVerifyClientCert

http:
  routers:
    internal-admin:
      rule: "Host(`admin.example.com`)"
      service: admin-service
      entryPoints: [websecure]
      tls:
        options: mtls-mandatory
      middlewares:
        - pass-client-cert
  middlewares:
    pass-client-cert:
      passTLSClientCert:
        pem: true
```

Для передачи аккуратных атрибутов (не PEM-блока) используйте `info`:

```yaml
passTLSClientCert:
  info:
    subject:
      commonName: true
```

### Сценарий 4: Дефолтный (самоподписанный) сертификат

Применяется, когда у Traefik нет сертификата для домена:

```yaml
tls:
  stores:
    default:
      defaultCertificate:
        certFile: /etc/traefik/certs/selfsigned.crt
        keyFile: /etc/traefik/certs/selfsigned.key
```

Учитывается только store с именем `default`. Вместо самоподписанного можно использовать сертификат от ACME: `defaultGeneratedCert.resolver`.

## Операции и команды

```bash
# Какие сертификаты/options реально подхвачены
curl -s http://localhost:8080/api/rawdata | jq '.tls.options' 
openssl s_client -connect app.example.com:443 -servername app.example.com </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates

# Проверка применяемой версии TLS
curl -sv https://app.example.com/ 2>&1 | grep -i "SSL connection"
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **TLS-хендшейк с устаревшим клиентом** | `minVersion` слишком высок | Снизьте до `VersionTLS12` или настройте отдельный профиль |
| **`421 Misdirected Request`** | Хост/SNI не совпадает с правилом или сертификатом | Проверьте `Host` и выданный сертификат |
| **Не применяются options из Docker-меток** | Options нельзя объявить в labels | Объявите в file provider, ссылайтесь `tls.options=myopt@file` |
| **mTLS: валидный клиент отклоняется** | `clientAuthType` `RequireAndVerifyClientCert` требует подпись выбранной CA | Добавьте CA в `caFiles` или используйте `VerifyClientCertIfGiven` |
| **Сертификат не подхватывается для домена** | Нет совпадающего роутера/сертификата для SNI | Задайте `tls.domains` или выпустите cert через ACME |
| **TCP-passthrough не работает** | Ожидалась терминация или наоборот | Проверьте флаг `passthrough: true` и протокол |

## Рекомендации

- Минимальный продакшн-стандарт: `minVersion: VersionTLS12`; для внутренних контуров — TLS 1.3 (`modern` профиль).
- Не задавайте `maxVersion` просто так: отключение TLS 1.3 ухудшает безопасность и совместимость.
- mTLS применяйте только там, где действительно нужно (админки, внутренние API), — оно усложняет эксплуатацию.
- Храните CA/ключи в защищенных путях с правами чтения только для процесса Traefik.
- Для публичных доменов используйте ACME-сертификаты вместо самоподписанных; самоподписанный — только как fallback.

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — ACME, роутеры, базовая настройка TLS.
- [Правила и приоритет](./traefik-routers-and-rules.md) — Host/HostSNI-матчеры.
- [Протоколы и потоки данных](./traefik-protocols-advanced.md) — TCP TLS, PROXY protocol, gRPC.
- [TLS-хардненинг для HTTP](../../Networking/Protocols/HTTP/http_tls_hardening.md) — общие принципы для веб-серверов.