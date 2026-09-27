# Traefik + CrowdSec: файрвол/WAF на edge

## Определения

**CrowdSec** — open-source IPS (система обнаружения и блокировки вторжений) на конфигурации «обучение по поведению»: анализирует логи, обменивается сигналами (IP-репутация) через сообщество, применяет банлисты на бянджере.

**Bouncer** — компонент CrowdSec, который реально блокирует: в случае Traefik это **плагин-баундер** (community-плагин `crowdsec-bouncer-traefik-plugin`), исполняемый внутри Traefik как middleware.

**LAPI (Local API)** — центральный сервис CrowdSec: принимает решения (киллслистное рейтинг ИП), связывает движок и бянджеры. Бянджер ходит в LAPI за актуальными «банами».

**AppSec (WAF-компонент)** — эндпоинт CrowdSec, выполняющий инспекцию запросов в режиме «виртуальный патч»: SQLi/XSS/см. детекции в реальном времени (цена — латентность ~мс). Включается тем же баундером через `crowdsecAppsecEnabled`.

**Сигнатура/детекция** — правило CrowdSec (YAML, тайм-окно + условия), например «>5 HTTP 4xx с одного IP за 10 сек».

## Базовые концепции

### Поток данных

```
 клиент ─▶ Traefik-entrypoint ──► middleware(brunter plugin)
                                   │  └─ аппсек-инспекция в реальном времени (AppSec)
                                   ▼
                        LAPI (CrowdSec)
                                   ▲        ▲
                    консультирование через фид данных (контекст/фид сообщества)
                                   │
                CrowdSec engine (агент): читает логи/события → баны
```

Два уровня защиты:

1. **Распределённое принятие решений (engine)** — IP-адреса, нарушившие правила (брутфорс, сканинг, 4xx-штормы), попадают в киллслист, который LAPI отдает баундеру; баундер возвращает `403` на запросы с этих IP.
2. **AppSec (WAF)** — инспекция тела запроса в реальном времени на SQLi/XSS (не зависит от репутации IP) — работает на `crowdsecAppsecEnabled: true`.

Баундер кэширует баны локально и обновляет их у LAPI — после рестарта Traefik список восстанавливается из LAPI; **это не теряется** (не как HTTP Provider).

### Где разместить bouncer

- Устанавливается как **plugin Traefik** (см. [Плагины Traefik](./traefik-plugins.md)) — не отдельный бинарник.
- В Docker-деплое достаточно добавить Traefik-контейнер в сеть с `crowdsec` (LAPI) и прописать key. Единый образ `crowdsecurity/crowdsec` поднимает движок+LAPI.
- Режимы `crowdsecMode`: `live`/`stream`/`alone`/`appsec` (см. официальную дку по баундеру). Для Traefik-екра обычно `live` (+ `crowdsecAppsecEnabled: true` для WAF).

## Практические сценарии

### Сценарий 1: Docker Compose: Traefik + CrowdSec (engine+LAPI bouncer)

```yaml
services:
  crowdsec:
    image: crowdsecurity/crowdsec:v1.6
    restart: unless-stopped
    environment:
      COLLECTIONS: "crowdsecurity/linux crowdsecurity/http-cve crowdsecurity/whitelists"
      GIN_MODE: release
    volumes:
      - crowdsec-db:/var/lib/crowdsec/data
      - ./crowdsec/acquis.yaml:/etc/crowdsec/acquis.yaml:ro   # источники логов
      # - ./crowdsec/parsers:/etc/crowdsec/parsers:ro
      - crowdsec-config:/etc/crowdsec
    ports:
      - "127.0.0.1:8080:8080"    # LAPI только на localhost!

  traefik:
    image: traefik:v3.7
    restart: unless-stopped
    command:
      - "--api.insecure=true"
      - "--entrypoints.web.address=:80"
      - "--providers.docker.exposedbydefault=false"
      # CrowdSec bouncer plugin
      - "--experimental.plugins.crowdsec-bouncer.modulename=github.com/maxlerebourg/crowdsec-bouncer-traefik-plugin"
      - "--experimental.plugins.crowdsec-bouncer.version=v1.5.0"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
    labels:
      - "traefik.enable=true"
      - "traefik.http.middlewares.crowdsec.plugin.crowdsec-bouncer.crowdsecLapiUrl=http://crowdsec:8080"
      - "traefik.http.middlewares.crowdsec.plugin.crowdsec-bouncer.crowdsecLapiKey=${CROWDSEC_LAPI_KEY}"
      - "traefik.http.middlewares.crowdsec.plugin.crowdsec-bouncer.crowdsecAppsecEnabled=true"
      - "traefik.http.middlewares.crowdsec.plugin.crowdsec-bouncer.forwardedHeadersTrustedIPs=0.0.0.0/0"

  app:
    image: httpd:2.4-alpine
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.app.rule=Host(`app.example.com`)"
      - "traefik.http.routers.app.middlewares=crowdsec@docker"
```

Получение LAPI-ключа (один раз):

```bash
docker exec crowdsec cscli bouncers add traefik-bouncer
# → API key: ...
export CROWDSEC_LAPI_KEY=...
docker compose up -d
```

Проверка, что баундер подключился и работает:

```bash
docker exec crowdsec cscli bouncers list
docker logs traefik | rg -i crowdsec
# Ожидаем: plugin loaded, баундер получил решения от LAPI
```

### Сценарий 2: Проверка блокировки

```bash
# Симулируем брутфорс с «плохого» IP: быстрые неправильные пароли/статусы
for i in $(seq 1 200); do curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Host: app.example.com" -u "admin:wrong$i" http://127.0.0.1/app/login; done
# Через несколько секунд источник попадает в киллслист движка CrowdSec,
# баундер отвечает 403: проверяем
curl -H "Host: app.example.com" -u "admin:wrong200" http://127.0.0.1/health
# → 403 Forbidden (бан от баундера)

docker exec crowdsec cscli decisions list
# → ✔ 192.168.1.5: * : bouncer named traefik-bouncer (4h)
```

### Сценарий 3: AppSec WAF (виртуальный патч SQLi/XSS)

В конфиге баундера включить `crowdsecAppsecEnabled: true` (как в Compose выше).

- Трафик с подозрительным телом инспектируется AppSec-компонентом; на совпадение с детекцией отдается `403` с идентификатором решения.
- Внимание: инспекция тел добавляет задержку — для приложений с большими/двоичными POST рисуйте реалистичный бенчмарк (размер тела, TPS).
- Параметризуется через файл правил AppSec (по умолчанию кор-коллекция `crowdsecurity/appsec` включена в образе).
- Если приложение валидирует тело повторно и вы получаете ложные срабатывания — смотрите `crowdsec`-логи `appsec` (парсер/код решения, причина) и исключайте ложноположительные слайсы (IP/детекция) через `exclusions`.

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **«Error getting bouncer token» в логах Traefik** | Неверный/просроченный LAPI-ключ, LAPI недоступен | Проверить `cscli bouncers list`, ключ в токене; доступность `http://crowdsec:8080` из сети Traefik |
| **Все запросы 403** | Accidentally `whitelists` отключены; собственный IP в черном списке; `forwardedHeadersTrustedIPs` с бочкой `0.0.0.0/0` | Убедиться, что CloudFront/IP-шлюз в trust; исключить доверенные IP в `whitelists` |
| **Ложные блокировки** | Аггрессивные коллекции / ложные срабатывания AppSec | Проверить `cscli alerts list`, поставить `exclusions`, сузить коллекции |
| **Баундер кэширует и не обновляет баны** | LAPI недоступен на время | Кэш-обновление по интервалу (уменьшить `crowdsecCacheSize`, проверить LAPI) |
| **WAF не инспектирует** | `crowdsecAppsecEnabled: false` либо AppSec-компонент не запущен | Включить флаг; в компоуз добавить service AppSec (порт 7422) |

## Рекомендации

- Режим продакшена: Traefik + **один** баундер, LAPI на protected/internal сети (не наружу).
- Помимо банов IP включайте `crowdsecAppsecEnabled` — защита от SQLi/XSS не зависит от репутации и дополняет киллслист.
- При использовании CDN (Cloudflare и т.п.) — обязательно настройте `forwardedHeadersTrustedIPs` и передавайте реальный IP, иначе баниться будет IP CDN.
- Обязательно мониторить отброшенные запросы: алерт при росте доли 403 от CrowdSec — возможна массовая атака или ложные срабатывания (метрики баундера — `traefik_middleware_request_total` + лог решений LAPI).
- Периодически ревью «решения» (`cscli decisions list`) — за 30 дней будет ясно, какие атаки реально идут на сервис.

## Дополнительная информация

- [Плагины Traefik](./traefik-plugins.md) — как ставятся и настраиваются community-плагины.
- [Обзор Traefik](./traefik_overview.md) — middleware-цепочка, forwardAuth/headers.
- [Прикладная безопасность: WAF](../../Security/ApplicationSecurity/waf.md) — классификация WAF и правила продвижения (эта музыка CrowdSec).
- [Traefik с Docker Compose](./traefik_with_docker_compose.md) — базовый паттерн Deploy за Docker.
- [Логирование и метрики Traefik](./traefik-observability.md) — как отслеживать поток отброшенных 403 и ставить SLO.