# Интеграция Cert-manager с Gateway API: Определения и концепции

## Определения

**Gateway API** — эволюция Kubernetes Ingress API, предоставляющая более выразительную модель для маршрутизации трафика (L7 и L4). Подробное описание: [Gateway API: Определения](../../../Networking/gateway_api/definitions.md).

**Интеграция с cert-manager:** cert-manager может автоматически выпускать сертификаты для Gateway-ресурсов через аннотации или прямые `Certificate` ресурсы. Поддержка включается флагом `--enable-gateway-api` (требуется cert-manager 1.13+).

**Требования:** установка CRD Gateway API **до** cert-manager. Подробности: [Определения cert-manager](../../definitions.md#интеграция-с-gateway-api), [Установка cert-manager](../../installation.md#включение-gateway-api).

---

## Основные концепции

### Поток работы при интеграции

```
1. Установка CRD Gateway API
         ↓
2. Установка cert-manager с --enable-gateway-api
         ↓
3. Создание Gateway с certificateRefs
         ↓
4. cert-manager создаёт Certificate (вручную или через аннотации)
         ↓
5. Secret создаётся и используется Gateway
```

### Отличия интеграции от Ingress

| Аспект | Ingress | Gateway API |
| :--- | :--- | :--- |
| **Аннотации** | `cert-manager.io/cluster-issuer` — автоматическое создание Certificate | Прямая ссылка на Secret в `certificateRefs` |
| **Certificate** | Создаётся автоматически через аннотацию на Ingress | Требуется вручную или через аннотации на Gateway |
| **Несколько слушателей** | Ограничено (один TLS-сертификат на Ingress) | Полная поддержка (отдельный Secret на слушатель) |
| **TLS-режимы** | Зависит от контроллера | `Terminate`, `Passthrough`, `Redirect` |
| **Hostname-конфликт** | Не возникает | cert-manager может некорректно определять домены из `hostname` слушателя |

---

## Практические сценарии

Подробные примеры настройки и манифесты (TLS Termination, прямые сертификаты, Gateway API) доступны в специализированном руководстве:

- **[Практические сценарии](./practical_scenarios.md)**

---

## Дополнительная информация

### Версии и совместимость

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| **cert-manager** | 1.13+ | Флаг `--enable-gateway-api` |
| **Gateway API CRD** | v1.0+ | Устанавливаются отдельно |
| **Kubernetes** | 1.21+ | Для Gateway API v1 |

### Смотрите также

- **[Gateway API: Дополнительные темы](./advanced_topics.md)** — диагностика интеграции и Hostname-конфликт
- **[Cert-manager: Определения](../../definitions.md)** — базовая совместимость
- **[Gateway API: Определения](../../../Networking/gateway_api/definitions.md)** — общие концепции маршрутизации
