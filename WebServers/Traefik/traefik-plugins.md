# Плагины в Traefik (Plugins)

**Актуально для:** Traefik v3.x (протестировано на v3.4–v3.6; с замечаниями по v2.11+)

## Определения

**Traefik Plugins** — программные модули расширения для Traefik, разрабатываемые на языке Go и исполняемые без полной перекомпиляции основного бинарного файла Traefik благодаря встроенному интерпретатору Yaegi.

**Yaegi (Yet Another Eli Lilly Go Engine)** — встроенный в бинарный дистрибутив Traefik интерпретатор исходного кода Go. Он выполняет синтаксический разбор (AST), компиляцию в байт-код и исполнение плагинов непосредственно в адресном пространстве процесса Traefik.

**Local plugins (`localPlugins`)** — плагины, исходный код которых размещается непосредственно в локальной файловой системе сервера или монтируется в контейнер по стандартному пути `plugins-local/src/<moduleName>`. Не требуют внешнего сетевого подключения и авторизации в сторонних каталогах.

**Community Catalog plugins (`plugins`)** — публичные плагины из каталога Traefik Hub / GitHub, скачиваемые сервером Traefik во время инициализации и сохраняемые в локальный кэш `plugins-storage`.

**Plugin manifest (`.traefik.yml` / `manifest.toml`)** — файл метаданных в корне репозитория плагина, определяющий тип плагина (`middleware` или `provider`), имя импорта Go-модуля, краткое описание и параметры тестовой конфигурации.

**Plugins storage (`plugins-storage`)** — служебная директория файловой системы, куда Traefik выгружает и распаковывает архивы внешних плагинов и их зависимостей перед запуском интерпретатора Yaegi.

**Middleware plugin** — тип плагина, реализующий интерфейс стандартного HTTP-обработчика Go (`http.Handler`) для перехвата, модификации, валидации или блокировки входящих клиентских запросов и ответов бэкендов.

**Provider plugin** — архитектурный тип плагина (поддерживается в Traefik v3+), расширяющий механизм обнаружения конфигурации Traefik. Позволяет динамически генерировать маршруты (routers), сервисы (services) и цепочки middleware из кастомных систем хранения данных или API.

## Базовые концепции и архитектура

### Жизненный цикл плагина в Traefik

Интеграция плагинов разделена на две фазы: статическую загрузку модуля ядром и динамическое связывание с маршрутизацией.

```
+--------------------------------------------------------------------------------+
| ФАЗА СТАТИЧЕСКОЙ ИНИЦИАЛИЗАЦИИ (Запуск Traefik)                                |
|                                                                                |
| 1. Чтение static config (traefik.yml / CLI flags)                              |
|    - experimental.plugins или experimental.localPlugins                        |
|                                                                                |
| 2. Загрузка исходного кода:                                                    |
|    - Каталог: HTTPS запрос к plugins.traefik.io / github.com -> plugins-storage |
|    - Локальный: чтение из ./plugins-local/src/<moduleName>                     |
|                                                                                |
| 3. Инициализация интерпретатора Yaegi:                                         |
|    - Парсинг AST, валидация интерфейсов и вызов New()                           |
+---------------------------------------+----------------------------------------+
                                        |
                                        v
+---------------------------------------+----------------------------------------+
| ФАЗА ДИНАМИЧЕСКОЙ ОБРАБОТКИ (Входящий трафик)                                  |
|                                                                                |
| 1. Входящий HTTP-запрос попадает на EntryPoint -> Router                       |
| 2. Выполнение цепочки Middlewares:                                             |
|    Native Middleware -> [ Yaegi Plugin: ServeHTTP() ] -> Native Middleware     |
| 3. Проксирование запроса к целевому Service                                    |
+--------------------------------------------------------------------------------+
```

1. **Объявление в статической конфигурации:** Плагин декларируется в секции `experimental.plugins` (для загрузки из каталога) или `experimental.localPlugins` (для локальных модулей). При старте Traefik проверяет декларации до инициализации сетевых интерфейсов (EntryPoints).
2. **Получение исходных текстов:** 
   - Для внешних плагинов Traefik выполняет HTTPS-запрос к API каталога, скачивает архив с кодом конкретной версии (Git tag) и распаковывает его в директорию `plugins-storage`.
   - Для локальных плагинов Traefik считывает файлы Go непосредственно из файловой системы по пути `./plugins-local/src/<moduleName>`.
3. **Компиляция и интерпретация Yaegi:** Движок Yaegi парсит исходные файлы Go в AST (Abstract Syntax Tree), проверяет экспортируемые функции `CreateConfig()` и `New()` и инстанциирует обработчик в памяти.
4. **Динамическое подключение к маршрутам:** В динамической конфигурации (`dynamic_conf.yml`, Docker Labels, File Provider) создается middleware с типом `plugin.<имя_плагина>`, передающим специфичный набор аргументов в фабрику конфигурации `CreateConfig()`.
5. **Исполнение в конвейере:** При прохождении запроса через роутер управление передается методу `ServeHTTP(rw http.ResponseWriter, req *http.Request)` скомпилированного Yaegi-модуля.

### Архитектурные ограничения среды Yaegi

Yaegi — это интерпретатор, а не полноценный JIT-компилятор. При эксплуатации плагинов в Production-окружениях системный администратор и SRE должны учитывать следующие технические особенности:
- **Отсутствие CGO:** Плагины не могут использовать C-библиотеки или вызовы CGO. Допускается только чистый Go-код.
- **Ограничения стандартной библиотеки:** Yaegi поддерживает большинство стандартных пакетов Go (`net/http`, `context`, `crypto`, `strings`, `time`), но не поддерживает пакеты или системные вызовы, требующие низкоуровневого ассемблера платформы.
- **Сторонние зависимости:** Сторонние зависимости плагина должны располагаться внутри директории `vendor/` самого плагина или быть частью стандартного дерева модулей Go, иначе Yaegi завершит загрузку с ошибкой отсутствия символов.
- **Накладные расходы по CPU и памяти:** Интерпретация логики Go через AST влечет дополнительное потребление процессорного времени (от 5x до 20x по сравнению с нативным кодом Traefik) и генерирует больше временных объектов в куче (heap), создавая дополнительную нагрузку на Go Garbage Collector (GC).

### Инфраструктурные требования: Bare-Metal, Systemd и Контейнеры

#### Взаимодействие с Systemd Security Sandbox
В жестко изолированных сервисах Linux systemd стандартные настройки безопасности могут блокировать работу плагинов:
- Директива `MemoryDenyWriteExecute=true` запрещает процессу создавать участки памяти, одновременно доступные для записи и исполнения (`PROT_WRITE` и `PROT_EXEC`). Движок Yaegi для генерации структур интерпретатора требует отключения этого флага (`MemoryDenyWriteExecute=false`), иначе ядро Linux завершит процесс Traefik аварийным сигналом `SIGSYS` или вернет ошибку `EPERM`.
- Ограничение файловой системы `ProtectSystem=strict` или `ReadOnlyPaths=/` требует явного открытия на запись каталога хранения кэша плагинов через директиву `ReadWritePaths=/var/lib/traefik/plugins-storage`.

#### Изолированные контуры (Air-Gapped / Offline Environments)
В корпоративных периметрах без прямого доступа в интернет автоматическая загрузка каталожных плагинов из `plugins.traefik.io` и `github.com` завершается тайм-аутом при старте Traefik, блокируя весь процесс.
Для изолированных контуров применяются два надежных подхода:
1. **Использование `localPlugins`:** Плагины скачиваются заранее на этапе сборки базового образа контейнера или развертываются через Ansible в локальный каталог `plugins-local`.
2. **Предварительное заполнение `plugins-storage`:** Директория кэша монтируется как Persistent Volume или pre-baked слой в контейнере с уже распакованным содержимым нужных версий.

## Практические сценарии и конфигурация

### Сценарий 1: Подключение Community-плагина в Docker Compose с персистентным кэшем

В данном сценарии подключается плагин для кастомного управления заголовками и авторизацией. Для исключения повторной загрузки из интернета при каждом перезапуске контейнера настраивается персистентный том для `/plugins-storage`.

Структура каталогов:
```
/opt/traefik/
├── docker-compose.yml
├── traefik.yml
└── dynamic/
    └── middlewares.yml
```

Статическая конфигурация (`traefik.yml`):

```yaml
entryPoints:
  web:
    address: ":80"
  websecure:
    address: ":443"

providers:
  file:
    directory: "/etc/traefik/dynamic"
    watch: true

# Декларация внешнего плагина из каталога
experimental:
  plugins:
    traefik-jwt-plugin:
      moduleName: "github.com/traefik-plugins/traefik-jwt-plugin"
      version: "v0.8.0"

log:
  level: "INFO"
  format: "json"
```

Динамическая конфигурация (`dynamic/middlewares.yml`):

```yaml
http:
  middlewares:
    auth-jwt:
      plugin:
        traefik-jwt-plugin:
          secret: "super-secure-production-secret-token"
          proxyHeaderName: "X-Auth-Payload"
          authHeader: "Authorization"

  routers:
    protected-api:
      rule: "Host(`api.internal.corp`)"
      entryPoints:
        - "websecure"
      service: "api-backend"
      middlewares:
        - "auth-jwt"

  services:
    api-backend:
      loadBalancer:
        servers:
          - url: "http://10.0.10.15:8080"
```

Файл развертывания (`docker-compose.yml`):

```yaml
services:
  traefik:
    image: traefik:v3.6.0
    container_name: traefik-edge
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /etc/localtime:/etc/localtime:ro
      - ./traefik.yml:/etc/traefik/traefik.yml:ro
      - ./dynamic:/etc/traefik/dynamic:ro
      # Персистентный кэш плагинов во избежание сетевых блокировок при рестарте
      - traefik_plugins_data:/plugins-storage
    networks:
      - edge_net

volumes:
  traefik_plugins_data:
    name: traefik_plugins_storage

networks:
  edge_net:
    driver: bridge
```

### Сценарий 2: Разработка и запуск собственного Local Plugin (On-Premise / Air-Gapped)

Создание локального middleware-плагина `request-id-injector`, который проверяет наличие входящего заголовка `X-Request-Id` и, если он отсутствует, генерирует уникальный идентификатор для трейсинга.

1. Создание структуры директорий под модуль `github.com/corp/request-id-injector`:

```bash
mkdir -p /opt/traefik/plugins-local/src/github.com/corp/request-id-injector
cd /opt/traefik/plugins-local/src/github.com/corp/request-id-injector
```

2. Инициализация `go.mod`:

```bash
cat << 'EOF' > go.mod
module github.com/corp/request-id-injector

go 1.22
EOF
```

3. Создание манифеста `.traefik.yml`:

```yaml
displayName: Request ID Injector
type: middleware
import: github.com/corp/request-id-injector
basePkg: request_id_injector
compatibility: v3
summary: Генерирует и проставляет заголовок X-Request-Id в случае его отсутствия.
testData:
  headerName: "X-Request-ID"
  forceOverride: false
```

4. Реализация логики плагина на Go (`request_id.go`):

```go
package request_id_injector

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"net/http"
)

// Config структура параметров конфигурации плагина
type Config struct {
	HeaderName    string `json:"headerName,omitempty" yaml:"headerName,omitempty"`
	ForceOverride bool   `json:"forceOverride,omitempty" yaml:"forceOverride,omitempty"`
}

// CreateConfig создает объект конфигурации с безопасными значениями по умолчанию
func CreateConfig() *Config {
	return &Config{
		HeaderName:    "X-Request-ID",
		ForceOverride: false,
	}
}

// RequestIdPlugin реализация обработчика
type RequestIdPlugin struct {
	next          http.Handler
	name          string
	headerName    string
	forceOverride bool
}

// New создает экземпляр плагина, вызываемый интерпретатором Yaegi
func New(ctx context.Context, next http.Handler, config *Config, name string) (http.Handler, error) {
	if config.HeaderName == "" {
		return nil, fmt.Errorf("headerName не может быть пустым")
	}

	return &RequestIdPlugin{
		next:          next,
		name:          name,
		headerName:    config.HeaderName,
		forceOverride: config.ForceOverride,
	}, nil
}

// generateRandomID генерирует псевдослучайный hex-идентификатор
func generateRandomID() string {
	bytes := make([]byte, 16)
	_, err := rand.Read(bytes)
	if err != nil {
		return "0000000000000000"
	}
	return hex.EncodeToString(bytes)
}

func (p *RequestIdPlugin) ServeHTTP(rw http.ResponseWriter, req *http.Request) {
	currentVal := req.Header.Get(p.headerName)

	if currentVal == "" || p.forceOverride {
		newID := generateRandomID()
		req.Header.Set(p.headerName, newID)
		rw.Header().Set(p.headerName, newID)
	} else {
		rw.Header().Set(p.headerName, currentVal)
	}

	p.next.ServeHTTP(rw, req)
}
```

5. Подключение в статической конфигурации Traefik (`/opt/traefik/traefik.yml`):

```yaml
experimental:
  localPlugins:
    request-id:
      moduleName: "github.com/corp/request-id-injector"

entryPoints:
  web:
    address: ":80"

providers:
  file:
    filename: "/opt/traefik/dynamic.yml"
    watch: true
```

6. Применение в динамической конфигурации (`/opt/traefik/dynamic.yml`):

```yaml
http:
  middlewares:
    inject-request-id:
      plugin:
        request-id:
          headerName: "X-Request-ID"
          forceOverride: false

  routers:
    app-router:
      rule: "Host(`service.corp.internal`)"
      entryPoints:
        - "web"
      middlewares:
        - "inject-request-id"
      service: "app-service"

  services:
    app-service:
      loadBalancer:
        servers:
          - url: "http://127.0.0.1:8080"
```

### Сценарий 3: Настройка Traefik на Bare-Metal с Systemd

Пример развертывания бинарного Traefik с поддержкой плагинов на выделенном Linux-сервере (RHEL/Debian) с жесткими политиками systemd.

Подготовка директорий и прав:

```bash
# Создание пользователя и системных директорий
sudo useradd -r -s /bin/false -U traefik
sudo mkdir -p /etc/traefik /var/lib/traefik/plugins-storage /var/log/traefik
sudo chown -R traefik:traefik /var/lib/traefik /var/log/traefik
sudo chmod 750 /var/lib/traefik/plugins-storage
```

Конфигурационный файл `/etc/traefik/traefik.yml`:

```yaml
entryPoints:
  web:
    address: ":80"

providers:
  file:
    directory: "/etc/traefik/conf.d"
    watch: true

# Указание каталога для кэширования плагинов
experimental:
  plugins:
    traefik-modsecurity:
      moduleName: "github.com/corazawaf/coraza-traefik-plugin"
      version: "v1.2.0"

log:
  level: "INFO"
  filePath: "/var/log/traefik/traefik.log"
```

Юнит-файл systemd `/etc/systemd/system/traefik.service`:

```ini
[Unit]
Description=Traefik Edge Reverse Proxy
Documentation=https://doc.traefik.io/traefik/
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=traefik
Group=traefik
ExecStart=/usr/local/bin/traefik --configfile=/etc/traefik/traefik.yml
Restart=always
RestartSec=5s
LimitNOFILE=65536

# Системная безопасность и изоляция
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectControlGroups=true
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=true

# КРИТИЧНО ДЛЯ ПЛАГИНОВ YAEGI:
# 1. Yaegi компилирует код в памяти -> запрет PROT_WRITE + PROT_EXEC сломает интерпретатор
MemoryDenyWriteExecute=false

# 2. Разрешение на запись в директорию кэширования скачиваемых плагинов
ReadWritePaths=/var/lib/traefik/plugins-storage /var/log/traefik

[Install]
WantedBy=multi-user.target
```

Применение юнита:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now traefik
sudo systemctl status traefik --no-pager
# → Active: active (running)
```

### Сценарий 4: Подключение Provider Plugin в Traefik v3

В Traefik v3 плагины могут выступать не только как middleware, но и как поставщики динамической конфигурации (Provider plugins), опрашивающие внутренние реестры, сервисы или файлы специального формата.

Статическая конфигурация (`traefik.yml`):

```yaml
experimental:
  plugins:
    custom-git-provider:
      moduleName: "github.com/example/traefik-git-provider"
      version: "v0.3.1"

# Активация провайдера через секцию providers.plugin
providers:
  plugin:
    custom-git-provider:
      pollInterval: "30s"
      repoUrl: "http://git.internal.corp/infra/routing-rules.git"
      branch: "main"
```

## Эксплуатация и мониторинг

### Валидация загруженных плагинов через Traefik API

Если включен внутренний API Traefik (`--api.insecure=true` или защищенный EntryPoint), состояние плагинов можно проинспектировать через CLI.

1. Проверка списка активных middleware с типом `plugin`:

```bash
curl -s http://127.0.0.1:8080/api/rawdata | jq '.middlewares | to_entries[] | select(.value.plugin != null) | {name: .key, plugin_info: .value.plugin}'
# → {
# →   "name": "inject-request-id@file",
# →   "plugin_info": {
# →     "request-id": {
# →       "forceOverride": false,
# →       "headerName": "X-Request-ID"
# →     }
# →   }
# → }
```

2. Проверка состояния роутеров, использующих плагин:

```bash
curl -s http://127.0.0.1:8080/api/http/routers | jq '.[] | select(.middlewares[]? | contains("plugin")) | {name: .name, status: .status, rule: .rule}'
# → {
# →   "name": "app-router@file",
# →   "status": "enabled",
# →   "rule": "Host(`service.corp.internal`)"
# → }
```

### Диагностика инициализации в логах

Для отладки этапов компиляции Yaegi уровень логирования переводится в режим `DEBUG`:

```bash
traefik --log.level=DEBUG --configfile=/etc/traefik/traefik.yml 2>&1 | grep -i "plugin"
# → DBG github.com/traefik/traefik/v3/pkg/plugins/plugins.go:62 > Plugins are enabled
# → DBG github.com/traefik/traefik/v3/pkg/plugins/local.go:34 > Loading local plugin: request-id
# → INF github.com/traefik/traefik/v3/pkg/server/server.go:120 > Plugin 'request-id' successfully loaded
```

### Локальная проверка совместимости плагина с Yaegi

Чтобы убедиться, что код плагина не содержит неподдерживаемых конструкций и синтаксических ошибок до развертывания в Traefik, используется автономная утилита Yaegi:

```bash
# Установка Yaegi CLI
go install github.com/traefik/yaegi/cmd/yaegi@latest

# Валидация интерпретации локального файла плагина
cd /opt/traefik/plugins-local/src/github.com/corp/request-id-injector
yaegi test -v .
# → === RUN   TestRequestIdPlugin
# → --- PASS: TestRequestIdPlugin (0.01s)
# → PASS
```

## Устранение неисправностей

| Симптом / Ошибка в логе | Первопричина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| `failed to download plugin: ... connection refused / timeout` | Нет прямого доступа в интернет (Air-gapped контур, закрытый DMZ, блокировка GitHub) | `curl -Iv https://plugins.traefik.io` с хоста Traefik | Перевести плагин в статус `localPlugins`, смонтировав код в `plugins-local`, либо предзагрузить архив в `plugins-storage` |
| Процесс завершается с кодом ошибки `SIGSYS` или `operation not permitted` | В systemd включен фильтр `MemoryDenyWriteExecute=true`, блокирующий JIT/генерацию памяти Yaegi | `journalctl -u traefik -e`, аудит auditd `type=SECCOMP` | Установить в юнит-файле `MemoryDenyWriteExecute=false` и выполнить `systemctl daemon-reload && systemctl restart traefik` |
| `open /plugins-storage/...: permission denied` | Процесс Traefik запущен от непривилегированного пользователя без прав записи в директорию кэша | `ls -ld /var/lib/traefik/plugins-storage` | Выполнить `chown -R traefik:traefik /var/lib/traefik/plugins-storage` и добавить путь в `ReadWritePaths` |
| `plugin not found: moduleName: github.com/...` | Нарушена структура каталогов для `localPlugins`. Traefik ожидает путь `plugins-local/src/<moduleName>` | `tree -L 4 plugins-local/` | Создать полный путь подкаталогов, в точности совпадающий со значением параметра `moduleName` |
| `field not found in configuration` | YAML-конфигурация динамического middleware передает параметры, отсутствующие в структуре `Config` в Go | Сравнить динамический конфиг с полями структуры `Config` плагина | Скорректировать ключи в секции `plugin.<name>`, соблюдая регистр символов и JSON/YAML-теги |
| `panic: runtime error: invalid memory address or nil pointer dereference` | Ошибка в Go-коде плагина при обработке непредусмотренных типов входящих запросов | Анализ полного stack trace в логах Traefik (`log.level=DEBUG`) | Добавить проверку на `nil` для структур `req.URL`, `req.TLS`, `req.Header` в функции `ServeHTTP` и протестировать через `yaegi test` |
| Рост задержки обработки запросов (высокий latency p99) | Тяжелые вычисления, блокирующие сетевые вызовы или аллокации памяти в цикле `ServeHTTP` | Снятие профилей CPU/Heap через pprof: `go tool pprof http://localhost:8080/debug/pprof/profile` | Оптимизировать код плагина, исключить синхронные сетевые запросы, перенести предварительные вычисления в конструктор `New()` |

## Рекомендации и Best Practices

- **Приоритет нативных механизмов:** Плагины следует использовать исключительно в ситуациях, когда стандартные компоненты Traefik не позволяют решить задачу. Для модификации заголовков, базовой аутентификации, ограничения частоты запросов (Rate Limiting) и CORS всегда используйте встроенные middleware (`headers`, `basicAuth`, `rateLimit`).
- **Запрет `version: latest`:** В production-среде строго запрещено указывать плавающий тег `latest` или ветку `master` в `experimental.plugins`. Всегда фиксируйте точный релизный тег (например, `version: v1.4.2`), чтобы исключить внезапное падение кластера при несовместимом обновлении внешнего репозитория.
- **Supply Chain Security:** Код плагина выполняется с правами процесса Traefik и имеет доступ ко всем сетевым потокам, токенам и сертификатам. Перед интеграцией стороннего community-плагина обязателен статический анализ и аудит исходного кода на предмет недекларированных сетевых соединений и утечек памяти.
- **Сборка production-образов с локальными плагинами:** Для контейнерных сред (Docker/Podman) оптимальной практикой для SRE является упаковка проверенного кода плагинов непосредственно в контейнерный образ на этапе CI/CD пайплайна:
  ```dockerfile
  FROM traefik:v3.6.0
  COPY ./my-plugins /plugins-local
  ```
  Это гарантирует неизменяемость инфраструктуры (immutable infrastructure) и полную независимость от доступности внешних сетевых каталогов при масштабировании узлов.
- **Контроль утечек горутин:** Если плагину требуется периодическое обновление данных (например, загрузка списков блокировок раз в минуту), горутина таймера должна быть привязана к контексту `context.Context`, переданному в функцию `New()`, чтобы корректно завершаться при перезагрузке конфигурации.
- **Очистка кэша плагинов:** При обновлении версий плагинов в директории `plugins-storage` могут накапливаться устаревшие распакованные архивы. Рекомендуется включить ротацию или очистку старых каталогов в регламент технического обслуживания серверов.

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — базовые концепции маршрутизации, архитектура и структура конфигурации.
- [Развертывание Traefik на Bare-Metal](./traefik-bare-metal.md) — настройка сервиса systemd, права доступа и тюнинг производительности сетевого стека Linux.
- [Traefik с Docker Compose](./traefik_with_docker_compose.md) — декларативное развертывание контейнеров, подключение томов и работа со статическими файлами.
- [Middleware для безопасности в Traefik](./traefik-middlewares-security.md) — обзор стандартных средств защиты: Headers, IP WhiteList, RateLimit.
- [Edge Security и WAF в Traefik](./traefik-edge-security-waf.md) — интеграция с WAF CrowdSec через плагин `crowdsec-bouncer-traefik-plugin`.
- [Отладка и профилирование Traefik](./traefik-debugging-performance.md) — анализ задержек, профилирование Go-рантайма через pprof и трейсинг запросов.
- [Каталог плагинов Traefik Hub](https://hub.traefik.io/plugins/) — официальный публичный реестр проверенных community-плагинов.
- [Репозиторий интерпретатора Yaegi](https://github.com/traefik/yaegi) — документация и исходный код движка исполнения Go.