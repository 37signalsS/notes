# Интеграция Cert-manager с Gateway API: Определения и концепции

## Определения

**Gateway API** — эволюция Kubernetes Ingress API, предоставляющая более выразительную модель для маршрутизации трафика (L7 и L4).

**Интеграция с cert-manager:** cert-manager может автоматически выпускать сертификаты для Gateway-ресурсов через аннотации или прямые `Certificate` ресурсы.

---

## Основные концепции

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| **cert-manager** | 1.13+ | Флаг `--enable-gateway-api` |
| **Gateway API CRD** | v1.0+ | Устанавливаются отдельно |
| **Kubernetes** | 1.21+ | Для Gateway API v1 |

### Поток работы

```
1. Установка CRD Gateway API
         ↓
2. Установка cert-manager с --enable-gateway-api
         ↓
3. Создание Gateway с certificateRefs
         ↓
4. cert-manager создаёт Certificate
         ↓
5. Secret создаётся и используется Gateway
```

### Отличия от Ingress

| Аспект | Ingress | Gateway API |
| :--- | :--- | :--- |
| **Аннотации** | `cert-manager.io/cluster-issuer` | Прямая ссылка на Secret |
| **Certificate** | Автоматически через аннотацию | Требуется вручную или через Gateway-аннотации |
| **Несколько слушателей** | Ограничено | Полная поддержка |
| **TLS-режимы** | Зависит от контроллера | `Terminate`, `Passthrough`, `Redirect` |

---

## Ссылки

- [Практические сценарии](./practical_scenarios.md) — настройка и использование
- [Дополнительная информация](./advanced_topics.md) — диагностика и особенности
