# Lens: Дополнительная информация

## Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Kubernetes | 1.20+ | Проверено до 1.32 |
| ОЗУ | 4 ГБ | Минимум, рекомендуется 8 ГБ |
| Дисковое пространство | 500 МБ | Для установки |

---

## OpenLens vs Lens Desktop

| Характеристика | OpenLens | Lens Desktop |
| :--- | :--- | :--- |
| **Лицензия** | MIT (открытая) | Commercial |
| **Расширения** | ✅ | ✅ |
| **Метрики** | ✅ | ✅ |
| **Поддержка** | Community | Commercial |
| **Обновления** | Реже | Чаще |

---

## Расширения (Extensions)

**Популярные расширения:**

- **Lens Metrics** — улучшенные метрики
- **Port Forwarder** — управление port forwarding
- **YAML Editor** — продвинутый редактор
- **GitOps** — интеграция с ArgoCD/Flux

**Установка:** `File > Preferences > Extensions` → найти расширение → нажать **Install**

---

## Безопасность

**Защита kubeconfig:** файлы kubeconfig содержат чувствительные данные, использовать права доступа `600`

**RBAC:** Lens использует права из kubeconfig, ограничить права для production-кластеров

**Отключение телеметрии:** `Preferences > Application > Telemetry`

---

## Ограничения

- **Ресурсоёмкость** — может потреблять значительную память (Electron-приложение)
- **Не заменяет kubectl** — сложные операции требуют CLI
- **Проприетарная версия** — Lens Desktop имеет платные функции (Teamwork, AI, Security Center)
- **Корпоративные прокси** — возможны конфликты с ZScaler и аналогичными SSL-inspection решениями
- **Активация** — требуется Lens ID (Online) или Offline activation mode

---

## Режимы развёртывания

**Standard mode** — стандартная работа с подключением к интернету для активации и обновлений.

**Air-gapped mode** — изолированная среда без выхода в интернет. Требуется offline-активация, обновления устанавливаются вручную. Security Center поддерживает сканирование в air-gapped.

**Hardened mode** — строгое управление доступом к функциям через Feature Management. Для корпоративных сред с повышенными требованиями к безопасности.

---

## Интеграции

**MCP Server (Model Context Protocol):** встроенный сервер для интеграции с AI-инструментами. Поддерживает готовые наборы для Kubernetes и Prometheus.

**AI-провайдеры (Lens Prism):** OpenAI, Azure OpenAI, любые API-совместимые endpoints. Конфигурация через `Preferences > AI`.

**SSO/SCIM:** корпоративная аутентификация через Microsoft Entra ID, Okta, JumpCloud.

**Lens Cloud:** облачная синхронизация для Teamwork-пространств.

---

## Альтернативы

- **[Octant](https://github.com/vmware-tanzu/octant)** — open source, лёгкий, от VMware
- **k9s** — TUI, терминальный интерфейс, быстрый
- **kubectl + vim** — CLI, полный контроль, скриптуемость

---

## Связанные ресурсы

**Репозитории и документация:**

- [GitHub: OpenLens](https://github.com/MuhammedKalkan/openlens)
- [GitHub: Lens](https://github.com/lensapp/lens)
- [Официальный сайт](https://k8slens.dev/)
- [Документация](https://docs.k8slens.dev/)

**Связанные файлы:**

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация о Lens
- [Практические сценарии](./practical_scenarios.md) — установка, настройка, использование
- [kubeswitches](../kubeswitches/usage.md) — управление контекстами
- [Prometheus API](../../../Prometheus/prometheus_api.md) — система метрик
- [Helm overview](../Helm/helm_overview.md) — управление чартами
- [Kubespray](../../Installation/Kubespray/kubespray_install/basic_concepts.md) — установка кластеров
