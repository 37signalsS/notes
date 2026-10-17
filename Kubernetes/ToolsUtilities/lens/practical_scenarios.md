**Актуально для:** Lens Desktop 2026.8 / FreeLens v1.10.3

# Lens: Практические сценарии

## Определения

**Lens (Lens Desktop)** — графическая IDE для Kubernetes, предназначенная для управления кластерами, визуализации ресурсов и автоматизации операций SRE и DevOps-инженеров.

**FreeLens** — активно поддерживаемый форк с открытым исходным кодом (лицензия MIT), созданный в 2024 году как преемник OpenLens. Не требует регистрации Lens ID, не содержит телеметрии. Последняя стабильная версия на июль 2026 — v1.10.3 (Electron 41, kubectl v1.36.2, Helm v4.2.2). Стандарт сообщества для бесплатного Kubernetes IDE.

**OpenLens** — классическая версия с открытым исходным кодом (лицензия MIT). Эффективно не поддерживается с конца 2024 года. Рекомендуется миграция на FreeLens.

**Kubeconfig** — конфигурационный файл в формате YAML, содержащий параметры подключения к кластерам Kubernetes.

**Helm** — менеджер пакетов для Kubernetes, используемый для управления жизненным циклом приложений (чартов).

**Lens Metric Stack** — встроенный стек мониторинга на базе Prometheus, развертываемый внутри кластера для визуализации метрик в IDE.

**Lens Prism** — встроенный AI-ассистент с контекстом кластера. Поддерживает режим Ask AI для запуска внешних CLI-агентов (Claude Code, Codex, Copilot CLI, Gemini CLI) прямо в терминале Lens. Режим подключения собственного LLM (BYOK) deprecated с 2026.6 в пользу интеграции с внешними AI-агентами.

**Lens MCP Server (Model Context Protocol)** — встроенный сервер для интеграции Lens с внешними AI-инструментами (Claude, Copilot) через стандартизированный протокол. Позволяет ИИ «видеть» состояние кластера в реальном времени.

**Air-gapped mode** — режим работы в изолированной среде без доступа к интернету. Требует предварительной загрузки всех бинарных файлов и образов. В FreeLens v1.10.0+ добавлена настройка зеркала kubectl в Preferences → Kubernetes → Kubectl.

**Hotbar** — панель быстрого доступа (до 12 кластеров на банк) с мгновенным переключением через клавиши F1–F12. Доступна в Pro/Enterprise редакциях Lens Desktop.

**Argo CD** — GitOps-инструмент для Kubernetes, предоставляющий declarative CD и визуальный дашборд приложений. Lens Desktop интегрирует Argo CD Applications, ApplicationSets, AppProjects, Repositories и Clusters с возможностью Sync и Refresh прямо из IDE (2026.8+).

**Gateway API** — стандартный набор ресурсов Kubernetes (Gateway, GatewayClass, HTTPRoute, GRPCRoute, TCPRoute, UDPRoute, TLSRoute, ReferenceGrant, BackendTLSPolicy, ListenerSet) для управления входящим трафиком. Lens предоставляет нативную навигацию и typed detail-панели для всех 10 ресурсов (2026.5+).

**ValidatingAdmissionPolicy / MutatingAdmissionPolicy** — нативные Kubernetes-политики валидации и мутации ресурсов на этапе admission, использующие CEL (Common Expression Language). Lens предоставляет структурированные detail-панели с подсветкой синтаксиса CEL.

**Hardened mode** — режим со строгим управлением функциями (Feature Management) для обеспечения безопасности в корпоративных средах. Позволяет отключать терминалы, AI-функции и внешние расширения.

---

## Основные концепции

### Философия "Visual Kubectl"

Lens абстрагирует сложные команды `kubectl` в интуитивно понятный графический интерфейс, работая как локальное приложение и используя текущие контексты `kubeconfig` пользователя. Это позволяет сократить время на диагностику и управление ресурсами.

### Ключевые возможности (2025–2026)

| Возможность | Описание |
| :--- | :--- |
| **Управление кластерами** | Поддержка сотен кластеров с мгновенным переключением контекстов. Автоматическое обнаружение kubeconfig. |
| **Hotbar** | Панель быстрого доступа до 12 кластеров на банк. Переключение F1–F12 / Shift+F1–F12 (Pro/Enterprise). |
| **Gateway API** | Полная навигация и typed detail-панели для всех 10 ресурсов Gateway API (2026.5+). |
| **Admission Policies** | Визуализация VAP/MAP с подсветкой CEL-выражений и шаблонами создания ресурсов (2026.5+). |
| **Argo CD** | Sync/Health дашборд, Application Sets, Repositories. Один клик для Sync/Refresh (2026.8+, Premium). |
| **Ask AI (AI Agent)** | Запуск Claude Code, Codex, Copilot CLI, Gemini CLI в терминале Lens с контекстом кластера. Без собственного API-ключа (2026.6+). |
| **Lens MCP Server** | Model Context Protocol для внешних AI-клиентов (Claude, Copilot, Codex). Кластерный контекст через MCP-инструменты (2026.3+). |
| **Security Center** | Сканирование образов Trivy. CIS- compliance. SBOM (Premium). |
| **Редактирование с diff** | Side-by-side diff редактор с возможностью отката к оригиналу (2026.8+, Premium). |
| **Port Forwarding** | Визуальное управление port forwarding без kubectl. Управление сессиями, открытие в браузере. |
| **Smart Terminal** | Терминал с контекстным autocompletion и синхронизацией окружения. |

### Требования к системе

| Компонент | Минимальная версия | Рекомендуется | Примечание |
| :--- | :--- | :--- | :--- |
| Kubernetes | 1.20+ | 1.28+ | Проверено до 1.36 |
| ОЗУ | 4 ГБ | 8 ГБ | Для работы с 10+ кластерами |
| Диск | 500 МБ | 1 ГБ | С учётом кэша образов и логов |
| kubectl | Совместимая с кластером | Бандл Lens v1.36.2 | Встроенный или пользовательский |
| Helm | v3+ / v4+ | Бандл Lens v4.2.2 | Встроенный или пользовательский |
| macOS | 12+ | 15 (Sequoia) | Universal Binary (Intel + Apple Silicon) |
| Windows | 10+ | 11 | |
| Linux | Ubuntu 20.04+ / Fedora 36+ | Ubuntu 24.04 | AppImage или deb |

### Сравнение редакций (2026)

| Характеристика | FreeLens | Lens Desktop (Personal) | Lens Desktop (Pro/Plus/Enterprise) |
| :--- | :--- | :--- | :--- |
| **Лицензия** | MIT (полностью open source) | Бесплатно для personal use | Коммерческая подписка ($14.90/user/mo+) |
| **Lens ID** | Не требуется | Обязателен | Обязателен |
| **Hotbar** | Нет | Нет | Да (Pro+) |
| **AI-агенты** | Ограничено (Extensions) | Ask AI (CLI-агенты) | Ask AI + MCP Server |
| **GitOps** | Базовый (Extensions) | Argo CD (read-only) | Argo CD (Sync/Refresh) |
| **Security Center** | Нет | Базовый | Полный (Trivy + CIS) |
| **Редактор с diff** | Нет | Базовый | Side-by-side diff + revert |
| **SSO/SCIM** | Нет | Нет | Да (Entra ID, Okta) |
| **Air-gapped** | Частично (зеркало kubectl) | Нет | Да (Offline Activation) |
| **Поддержка** | Community (GitHub) | Mirantis | Mirantis (SLA) |
| **Electron / kubectl** | v41 / v1.36.2 | Актуальный | Актуальный |

---

## Практические сценарии

### Установка

**macOS (Homebrew):**

```bash
# FreeLens (рекомендуется для Open Source окружений)
brew install --cask freelens

# Lens Desktop (коммерческая версия с полным набором функций)
brew install --cask lens
```

**Windows (Chocolatey / Winget):**

```bash
# Chocolatey
choco install kubernetes-lens

# Winget
winget install Mirantis.Lens
```

**Linux (Ubuntu/Debian):**

```bash
# Добавление репозитория для Lens Desktop
curl -fsSL https://api.k8slens.dev/repos/deb/gpg.key | sudo apt-key add -
echo "deb https://api.k8slens.dev/repos/deb/ /" | sudo tee /etc/apt/sources.list.d/lens-repo.list
sudo apt update && sudo apt install lens
```

Для **FreeLens** на Linux рекомендуется использовать официальные AppImage из GitHub-репозитория проекта:
```bash
chmod +x FreeLens-*.AppImage && ./FreeLens-*.AppImage
```

**Проверка версии:** Help → About Lens / About FreeLens. Версия отображается в формате `Год.Месяц.Сборка` (Lens) или `vX.Y.Z` (FreeLens).

### Начальная настройка

**Подключение к кластеру:** Lens основывается на текущих файлах `kubeconfig`.
- **Автоматическое обнаружение:** приложение сканирует `~/.kube/config` и стандартные пути (`/etc/kubernetes/admin.conf`, KUBECONFIG). Все найденные контексты отображаются в списке.
- **Ручное добавление:** File → Add Cluster (или `⌘/Ctrl + K`) → вставить содержимое конфига или выбрать файл на диске.
- **Onboarding Wizard (2026.3+):** При первом запуске пошаговый помощник помогает подключить облачные кластеры (EKS/AKS) и импортировать локальные kubeconfig.

**Настройка путей:** Preferences → Kubernetes → укажите дополнительные пути к директориям с файлами конфигурации, если они хранятся вне стандартного пути.

**Настройка kubectl и Helm:** Preferences → Kubernetes → Kubectl / Helm — можно указать пользовательские бинарники или использовать встроенные (рекомендуется). В FreeLens v1.10.0+ доступна настройка зеркала kubectl для air-gapped сред.

### Настройка метрик

По умолчанию метрики могут отображать статус `metrics not available`.

**Вариант 1: Встроенный Lens Metric Stack**
ПКМ на кластер в боковой панели → Settings → Lens Metrics → Install. Приложение развернет Prometheus и необходимые компоненты внутри кластера.
- Преимущество: минимум настроек.
- Недостаток: требует StorageClass по умолчанию; может конфликтовать с уже установленным Prometheus.
- Диагностика: проверьте логи пода `lens-metrics` в namespace `lens-metrics`.

**Вариант 2: Существующий Prometheus**
Cluster Settings → Metrics → Custom Prometheus → укажите URL API. Например:
```
http://prometheus-operated.monitoring.svc.cluster.local:9090
```
- Преимущество: использует существующую инфраструктуру мониторинга.
- Требования: Prometheus должен быть доступен из Lens (внутри кластера или через port-forward).
- FreeLens: поддержка OpenShift Prometheus с bearer token аутентификацией (v1.9.0+). Переключение метода запроса GET/POST в настройках Prometheus.

### Управление расширениями

Расширения значительно дополняют функционал IDE.
- **Установка:** File → Extensions (или `⌘/Ctrl + Shift + E`) → вставьте ссылку на расширение или выберите локальный архив.
- **Рекомендуемые расширения (FreeLens):**
    - `@freelens/metrics` — расширенные визуализации для FreeLens.
    - `@freelens/node-shell` — доступ к нодам через shell.
   - `@argoproj/argo-cd-extension` — отображение статуса приложений ArgoCD.
- **Совместимость:** Большинство расширений OpenLens работают в FreeLens, но могут потребовать обновления. Проверяйте в [FreeLens Extensions Discussion](https://github.com/freelensapp/freelens/discussions/2291).
- **Lens Desktop:** Расширения доступны в маркетплейсе Lens (Pro/Enterprise).

### Управление Helm-чартами

Lens поддерживает Helm v3/v4 и работу с OCI-репозиториями.
- **Просмотр:** Выберите кластер → раздел Helm → Charts / Releases.
- **Добавление репозитория:** Preferences → Kubernetes → Helm Charts → добавить HTTP или OCI-репозиторий.
  - OCI-формат: полный путь к чарту (например, `oci://ghcr.io/stefanprodan/charts/podinfo`), а не корень репозитория.
- **Установка:** Найдите нужный чарт → Install → настройте `values.yaml` непосредственно в редакторе Lens.
- **Обновление:** Helm → Releases → выберите релиз → Upgrade. Версии отфильтровываются по репозиторию релиза (исправлено в 2026.8).
- **Откат:** Helm → Releases → выберите релиз → Rollback → укажите ревизию.
- **Удаление:** Helm → Releases → выберите релиз → Uninstall.

### Работа с AI-ассистентом (Lens Prism и MCP)

**Lens Prism — Ask AI (рекомендуется, 2026.6+):**
Режим BYOK (привязка собственного LLM) deprecated. Рекомендуется использование внешних CLI-агентов.
1. Установите один из поддерживаемых агентов на локальную машину (Claude Code, GitHub Copilot CLI, Gemini CLI, Codex).
2. Lens автоматически обнаруживает установленные CLI-агенты. Выбор агента: Preferences → External Tools.
3. Откройте терминал в Lens (контекст кластера автоматически пробрасывается через `KUBECONFIG`).
4. Используйте ПКМ на любом ресурсе → Ask AI → выберите действие:
   - Summarize resource — краткое описание состояния ресурса.
   - Analyze logs/events/metrics — анализ логов, событий или метрик.
   - Look at related resources — поиск связанных ресурсов.
5. Агент стартует с контекстом кластера и `CLAUDE.md` / `GEMINI.md` (при наличии).

**Lens MCP Server (для внешних AI-клиентов):**
Интеграция позволяет внешним ИИ-агентам (Claude Desktop, Codex, Copilot) получать контекст кластера напрямую.
1. Включите сервер в Preferences → Terminal → MCP Server.
2. MCP-инструменты включают: kubectl execution, Prometheus metrics, cluster info.
3. В клиенте (например, Claude Desktop) добавьте конфигурацию:
```json
{
  "mcpServers": {
    "lens": {
      "command": "lens-mcp-server",
      "args": ["--port", "3000"]
    }
  }
}
```
4. Теперь ИИ может отвечать на вопросы типа «Какие поды находятся в состоянии Error?» на основе данных из Lens.

**FreeLens — AI через Extensions:**
FreeLens не включает Lens Prism. AI-функции доступны через community-расширения или внешние инструменты, запускаемые в терминале.

### Работа в изолированной среде (Air-gapped)

Для использования Lens в закрытых контурах:
1. **Предварительная загрузка:** Скачайте инсталлятор и необходимые расширения (`.tar.gz`) на машину с доступом в интернет.
2. **Оффлайн-активация:** Для Lens Desktop Pro используйте Offline Activation через генерацию файла запроса лицензии.
3. **Настройка Helm:** Добавьте локальный Harbor или другой OCI-репозиторий в Preferences → Kubernetes → Helm Charts.
4. **Метрики:** Используйте Вариант 2 (подключение к уже существующему в кластере Prometheus), так как встроенная установка может потребовать доступа к публичным реестрам для загрузки образов Prometheus Stack.
5. **Зеркало kubectl (FreeLens v1.10.0+):** Preferences → Kubernetes → Kubectl → Custom download mirror URL. Укажите URL внутреннего зеркала для скачивания kubectl.
6. **FreeLens SOCKS5:** В v1.10.3+ API-прокси поддерживает SOCKS5 для upgrade-запросов (exec, attach, port-forward), что позволяет работать через SOCKS5-прокси в изолированных средах.

### Корпоративная безопасность (Hardened Mode)

В крупных организациях администраторы могут ограничивать функции Lens:
- **Отключение расширений:** Блокировка установки сторонних плагинов через политики безопасности.
- **RBAC:** Использование Lens совместно с инструментами типа `teleport` или `boundary` для прозрачной аутентификации без хранения долгоживущих токенов в `kubeconfig`.
- **Прокси:** Настройка системного прокси в Preferences → Application → Proxy. Поддержка SOCKS5 для upgrade-запросов (exec, attach, port-forward) в FreeLens v1.10.3+.

### Port Forwarding

Lens позволяет настраивать port forwarding без kubectl из GUI:
1. **Быстрый запуск:** Workloads → Pods → выберите под → вкладка Container → нажмите на порт (например, `8000/TCP`). Lens назначит локальный порт и откроет браузер.
2. **Ручная настройка:** Кнопка Forward → укажите локальный порт, удалённый порт, протокол (TCP/UDP).
3. **Управление сессиями:** Вкладка Port Forwarding в нижней панели — список активных сессий с возможностью открыть в браузере, редактировать, остановить или удалить.
4. **Просмотр:** Colon КМ на поде → Port Forwarding → таблица с columns: Name, Namespace, Kind, Pod Port, Local Port, Protocol, Status.

**Примечание:** Port forwarding — временный механизм для отладки. Для persistent connectivity используйте LoadBalancer или Ingress.

### Hotbar (Pro/Enterprise)

Панель быстрого доступа для мгновенного переключения между кластерами:
1. **Добавление кластера:** ПКМ на кластере в Navigator → Add to Hotbar.
2. **Банки:** До 12 кластеров на банк (столбец). Управление через Command Palette:
   - `Ctrl+Shift+P` → `hotbar: create bank` — создать новый банк.
   - `Ctrl+Shift+P` → `hotbar: rename bank` — переименовать.
   - `Ctrl+Shift+P` → `hotbar: remove bank` — удалить.
3. **Переключение:** `F1`–`F12` — кластеры в текущем банке. `Shift+F1`–`Shift+F12` — переключение банков.
4. **Bottom Tray:** При переключении контекста через Hotbar нижняя панель (терминалы, логи, редакторы) автоматически фильтруется по активному контексту.

### Редактирование ресурсов и Side-by-Side Diff

Lens предоставляет интегрированный редактор YAML с расширенными возможностями:
1. **Открытие редактора:** ПКМ на ресурсе → Edit (или `⌘/Ctrl + E`).
2. **Side-by-Side Diff (2026.8+, Premium):** В редакторе нажмите иконку diff — отображается ORIGINAL vs CHANGED с подсветкой различий.
3. **Откат:** Кнопка Revert восстанавливает оригинальное состояние одним кликом.
4. **Сохранение:** Save and Close применяет манифест через kubectl apply (Server-Side Apply по умолчанию в Lens).

**Примечание:** Редактирование доступно только для ресурсов, к которым у пользователя есть права RBAC (verbs: get, update, patch).

### Интеграция с Argo CD

С 2026.8 Lens предоставляет полную интеграцию с Argo CD:
1. **Навигатор:** Группа Argo CD содержит: Applications, ApplicationSets, AppProjects, Repositories, Clusters.
2. **Dashboard:** Сводка Sync/Health. Список "Needs attention" для приложений, требующих внимания. Лента "Recent activity" с последними sync-событиями.
3. **Управление:** Sync/Refresh — одним кликом (или пакетно для нескольких приложений). Переход на веб-интерфейс Argo CD — кнопка "Open UI".
4. **Связь с workload:** Из Argo CD Application → jump to managed resources. Обратная навигация из workload → Argo CD Application.
5. **Ask AI:** ПКМ на любой Argo CD-ресурсе → Ask AI.

**Примечание:** Argo CD Dashboard — Premium-функция. Требует Argo CD в кластере.

### Управление Gateway API ресурсами

С 2026.5 Lens предоставляет нативную поддержку всех 10 ресурсов Gateway API:
1. **Навигатор:** Отдельная группа "Gateway API" (появляется на кластерах с установленным Gateway API). Содержит: Gateway, GatewayClass, HTTPRoute, GRPCRoute, TCPRoute, UDPRoute, TLSRoute, ReferenceGrant, BackendTLSPolicy, ListenerSet.
2. **Detail-панели:** Каждый ресурс имеет типизированную панель:
   - Gateway → Properties, Listeners, attached Routes.
   - HTTPRoute → Hostnames, Rules, Backends.
   - Service → вкладка Routes (все Gateway API Routes, targeting данную Service).
3. **Создание:** Create Resource dialog с шаблонами для каждого типа ресурса.
4. **Ask AI:** ПКМ → Ask AI → Explain route / Trace traffic flow.

### Onboarding Wizard (2026.3+)

Для новых пользователей Lens предоставляет пошагового помощника:
1. Запуск при первом запуске или через Help → Onboarding Wizard.
2. Шаги: подключение облачных кластеров (EKS/AKS), импорт локальных kubeconfig, настройка AI-интеграций.
3. Помощник помогает настроить Lens Prism (AI) и cloud-провайдеры.

### Мониторинг и диагностика

- **Просмотр логов:** Workloads → Pods → выберите под → кнопка **Logs**. Поддерживается фильтрация по времени, текстовый поиск, word wrap (вкладка Toggle), отображение предыдущих terminated-контейнеров. Настройки отображаются глобально и сохраняются между сессиями.
- **Предыдущие логи:** Кнопка "Show previous terminated container" для просмотра логов из crash-loop контейнеров.
- **Встроенный терминал:** Кнопка Shell на уровне пода или узла. Автоматически пробрасывает переменные окружения и контекст кластера. Поддержка привязки к конкретному контейнеру через аннотацию `kubectl.kubernetes.io/default-container`.
- **Port Forwarding:** Визуальное управление port forwarding (см. раздел Port Forwarding).
- **Security Center:** Раздел Security в меню кластера. Сканирование Trivy для поиска CVE в запущенных образах и конфигурациях. SBOM-генерация.
- **Метрики ресурсов:** Графики CPU/Memory для подов, нод и деплойментов. Поддержка Prometheus Operator (ServiceMonitor/PodMonitor). Time range selector (1h, 3h, 24h, 7d, custom).
- **События:** Просмотр Events с фильтрацией по типу (Warning, Normal). Поддержка events.k8s.io/v1 с source и repeat count.

### Интеграция с Kubespray

При использовании кластеров, развернутых через [Kubespray](../../Installation/Kubespray/kubespray_install/basic_concepts.md):

```bash
# Импорт конфига из директории инвентаря
cp inventory/my_cluster/artifacts/admin.conf ~/.kube/config

# Или через KUBECONFIG
export KUBECONFIG=inventory/my_cluster/artifacts/admin.conf
```

Lens автоматически обнаружит импортированный контекст. Для работы с несколькими кластерами Kubespray рекомендуется использовать kubeswitch (см. [kubeswitch_overview.md](../kubeswitch_overview.md)).

---

## Дополнительная информация

### Горячие клавиши

| Комбинация | Действие |
| :--- | :--- |
| `⌘/Ctrl + K` | Command Palette (быстрый поиск и навигация) |
| `⌘/Ctrl + E` | Открыть редактор текущего ресурса |
| `⌘/Ctrl + Shift + E` | Управление расширениями (Extensions) |
| `⌘/Ctrl + Shift + P` | Command Palette (альтернатива) |
| `F1`–`F12` | Переключение кластеров в текущем банке Hotbar |
| `Shift+F1`–`Shift+F12` | Переключение банков Hotbar |
| `⌘/Ctrl + `` | Открыть/скрыть терминал |
| `⌘/Ctrl + ,` | Preferences (Настройки) |
| `⌘/Ctrl + F` | Поиск в текущем контексте (логи, ресурсы) |
| `Esc` | Закрыть активный диалог или панель |

### Deep Links (lens://)

Lens поддерживает deep links для прямого перехода к ресурсам:
- `lens://catalog` — открыть каталог кластеров.
- `lens://cluster/<cluster-name>` — подключиться к конкретному кластеру.
- `lens://cluster/<cluster-name>/workloads/pods` — перейти к подам кластера.
- `lens://cluster/<cluster-name>/config/config-maps` — перейти к ConfigMaps.

Deep links работают из браузера, терминала или других приложений.

### Безопасность

- **RBAC:** Lens строго следует правам текущего контекста. Если у вас нет прав на чтение Secret, IDE их не отобразит.
- **Защита kubeconfig:** Файлы конфигурации содержат чувствительные данные. Устанавливайте права доступа `600` на локальные файлы.
- **Телеметрия:** Сбор данных можно отключить в Preferences → Application → Telemetry. FreeLens не содержит телеметрии.
- **OIDC:** Lens поддерживает kubelogin-плагин для аутентификации через OIDC с MFA и PKCE (без долгоживущих токенов в kubeconfig).

### Устранение неполадок

- **Корпоративные прокси (ZScaler и др.):** Если возникают ошибки аутентификации, необходимо настроить исключения SSL-инспекции для доменов `k8slens.dev`. Проверьте настройки прокси в Preferences → Application → Proxy.
- **Ошибка подключения к Shell:** Убедитесь, что у вас есть права на операцию `exec` в RBAC и API-сервер доступен с вашей машины. Проверьте: `kubectl auth can-i create pods/exec --namespace=<ns>`.
- **Высокое потребление ресурсов:** При работе с десятками кластеров Lens может потреблять значительный объем ОЗУ. Рекомендуется отключать неиспользуемые кластеры (ПКМ → Disconnect) или использовать Hotbar для переключения.
- **Конфликты Lens Metric Stack:** Если после установки встроенных метрик графики не отображаются, проверьте логи пода `lens-metrics` в пространстве имен `lens-metrics`. Частая причина — отсутствие `StorageClass` по умолчанию для Prometheus.
- **Проблемы MCP Server:** Если внешние ИИ не видят кластер, убедитесь, что порт (по умолчанию 3000) не занят другим приложением и Lens запущен. Проверьте логи MCP-сервера.
- **Чёрное окно при запуске:** В Lens 2026.8+ исправлена проблема с чёрным окном при краше renderer-а. Обновите до последней версии.
- **Helm: Failed to parse helm value:** Ошибка возникает, когда плагин пишет warning в stdout. Обновите Lens — проблема решена в 2026.6+.
- **AKS Azure SSO login fails:** Оставшийся orphaned lock от предыдущей сессии. Lens 2026.6+ автоматически очищает stale lock перед входом.
- **EKS на ограниченных AWS Orgs:** Если `eks:ListClusters` ограничен подмножеством регионов, Lens 2026.6+ запоминает отклонённые регионы и пропускает их, предотвращая loops.
- **Namespace filter recovery:** Если выбранные namespace больше не разрешены, фильтр автоматически восстанавливается (2026.8+).
- **FreeLens: kubectl binary removal:** В v1.10.3 исправлена ошибка, когда bundled kubectl удалялся при EBUSY-ошибке (Windows).
- **FreeLens: Prometheus query failures:** В v1.10.3 исправлены запросы при дублирующихся сериях `kube_pod_info` с flap-метками `pod_ip`/`host_ip`.

### Альтернативные инструменты

- **k9s** — терминальный интерфейс (TUI) для быстрой работы. Отличный вариант для серверов без GUI.
- **Headlamp** — современный расширяемый веб-интерфейс (CNCF Sandbox). Устанавливается через Helm.
- **kubectl + vim** — классический подход для максимального контроля.
- **Rancher** — веб-интерфейс для управления несколькими кластерами с RBAC и GitOps.

### Миграция с OpenLens на FreeLens

OpenLens эффективно не поддерживается с конца 2024 года. Рекомендуется миграция:
1. Скачайте FreeLens с [freelens.app](https://freelens.app).
2. Конфигурации kubeconfig автоматически переносятся — FreeLens читает тот же `~/.kube/config`.
3. Расширения OpenLens могут потребовать обновления. Проверьте совместимость в FreeLens extension registry.
4. Удалите OpenLens после убедительной работы FreeLens.

### Связанные ресурсы

- [kubeswitch_overview.md](../kubeswitch_overview.md) — эффективное управление контекстами.
- [Helm overview](../Helm/helm_overview.md) — основы управления чартами.
- [Prometheus API](../../../Prometheus/prometheus_api.md) — описание API системы метрик.
- [Kubernetes Dashboard](../../kubernetes-dashboard.md) — сравнение альтернативных веб-интерфейсов.
