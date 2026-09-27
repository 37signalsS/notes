# Плагины в Traefik (experimental)

## Определения

**Experimental plugins** — модули, расширяющие Traefik новыми middleware и протоколами, загружаемые через `experimental.plugins`.

**Plugin manifest** — метаданные плагина (`manifest.toml`) с именем, версией, зависимостями и типом.

**Local plugins** — плагины, загружаемые из локальной директории `plugins-local` без публикации в каталог Traefik Hub/Plugin store.

## Базовые концепции

### Как работают плагины

Плагины — это middleware, написанные на Go с использованием Traefik Plugin SDK (Yaegi-интерпретатор). Они объявляются в **статической** конфигурации и, после загрузки, подключаются к роутеру как обычный референсный middleware.

Объявление (static):

```yaml
experimental:
  plugins:
    traefik-cors:
      moduleName: github.com/maxmind/traefik-cors
      version: v0.7.1
```

Использование в динамической конфигурации (file):

```yaml
http:
  middlewares:
    my-cors:
      plugin:
        traefik-cors:
          origins:
            - "https://app.example.com"
  routers:
    app:
      rule: "Host(`app.example.com`)"
      middlewares:
        - my-cors
```

Параметры плагина — это YAML-объект с настройками под конкретный плагин (схема прописана в манифесте).

### Local plugins (plugins-local)

Загружаются из поддиректории рядом с исполняемым файлом Traefik (или из `--plugins.local`):

```
plugins-local/
  src/github.com/maxmind/traefik-cors/
    manifest.toml
    traefik-cors.go
    ...
```

```yaml
experimental:
  localPlugins:
    traefik-cors:
      moduleName: github.com/maxmind/traefik-cors    # local, без version
```

Требования: имя модуля в Go-пути уникально и не равно авторизованным third-party.

### Каталог плагинов

Каталог community-плагинов — [Traefik Hub Plugin Catalog](https://hub.traefik.io/plugins/). Также `github.com/traefik/plugin-catalog-open-source` — список открытых плагинов (demos, auth, security, headers, etc.). В репозиториях плагинов есть собственный CI для тестов под версии Traefik.

### Требования безопасности

- Плагин исполняет произвольный код внутри Traefik — проверяйте репозиторий, лицензии, cфокусируйте `version` (а не `latest`).
- В v3 `experimental.plugins` — глобальный механизм; для серьезных продов плагины лучше тестировать на отдельном инстансе (поглощение ресурсов Yaegi, вариант — бинарная сборка Traefik с плагинами через Traefik Plugin - builder) , доступен `plugins.local` для локальной разработки.

## Практические сценарии

### Сценарий 1: Упрощение CORS (плагином)

```yaml
experimental:
  plugins:
    traefik-cors:
      moduleName: github.com/maxmind/traefik-cors
      version: v0.7.1
```

```yaml
http:
  routers:
    public-api:
      rule: "Host(`api.example.com`)"
      middlewares:
        - cors-plugin
  middlewares:
    cors-plugin:
      plugin:
        traefik-cors:
          origins: ["*"]
```

Обычно подходит и стандартный `headers` (см. [Middleware для безопасности](./traefik-middlewares-security.md)) — плагин без необходимости повышает риски.

### Сценарий 2: Локальная разработка плагина

```bash
mkdir -p plugins-local/src/github.com/me/my-plugin
cd plugins-local/src/github.com/me/my-plugin
# → manifest.toml, my-plugin.go (с обяз. методами middleware), go.mod
```

Запуск Traefik с локальным каталогом:

```bash
traefik --experimental.localPlugins.my-plugin.moduleName=github.com/me/my-plugin \
        --providers.docker=true
```

### Сценарий 3: Проверка загрузки и работоспособности

```bash
# Дашборд → "Plugins" (или /api/rawdata)
curl -s localhost:8080/api/rawdata | jq '.middlewares'
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Плагин не загружен (warn в логах)** | Неверный `moduleName`/`version`, нет `experimental.plugins` | Проверьте манифест и лог загрузки |
| **`ModuleNotFound` при запуске** | Local-плагин вне `plugins-local`, неверный путь | Поместите в `src/<moduleName>` |
| **Middleware не работает / все 500** | Плагин под несовместимую версию Traefik | Текущую версию плагина посмотрите в каталоге; протестируйте отдельно |
| **Роутер регуляторно падает** | Исключение внутри плагина (Yaegi) | Смотрите stack trace в логах, обновите/замените плагин |
| **Параметр не принимается плагином** | Несовпадение схемы YAML с manifest | Сверьте поля с `configuration` в manifest.toml |

## Рекомендации

- Плагины — только когда стандартные middleware не покрывают задачу. Для CORS/auth/headers обычно хватает встроенных.
- Фиксируйте точную версию плагина; не используйте «latest».
- Локальные плагины держите под контролем версионирования кода (git).
- В кластере подключайте плагин только после отдельного инстанса-теста.
- Следите за update-зависями плагинов под актуальные трафиковые версии.

## Дополнительная информация

- [Middleware для безопасности](./traefik-middlewares-security.md) — встроенные Headers/CORS.
- [Каталог плагинов Traefik Hub](https://hub.traefik.io/plugins/) — официальный список community-плагинов.
- [Обзор Traefik](./traefik_overview.md) — статическая конфигурация и YAML-манифесты.