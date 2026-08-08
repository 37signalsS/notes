# ArgoCD Notifications — настройка уведомлений

## Определения

**ArgoCD Notifications** — встроенный компонент ArgoCD (начиная с v3.x), предназначенный для мониторинга событий жизненного цикла приложений и отправки уведомлений во внешние системы (Slack, Telegram, Email и др.).

**Триггер (Trigger)** — логическое условие на базе языка выражений (Expression Language), при выполнении которого инициируется отправка уведомления.

**Шаблон (Template)** — структура и содержание сообщения, формируемого с использованием Go-шаблонов на основе данных о событии.

**Сервис (Service)** — конфигурация подключения к внешней платформе доставки (API токены, URL вебхуков).

**Подписка (Subscription)** — связка триггера, приложения и конкретного получателя (канала, почтового адреса).

## Основные концепции

### Архитектура в версии v3.x

В современных версиях функционал уведомлений полностью интегрирован в **argocd-application-controller**. Это исключает необходимость запуска отдельного контроллера для уведомлений в небольших инсталляциях.

**Конфигурационные ресурсы:**
1. **`argocd-notifications-cm`:** Содержит описание триггеров, шаблонов и сервисов.
2. **`argocd-notifications-secret`:** Хранит чувствительные данные (токены, пароли).

### Жизненный цикл уведомления

1. **Событие:** Изменение статуса приложения (например, `OutOfSync` или `Degraded`).
2. **Оценка:** Контроллер проверяет все активные подписки для данного приложения.
3. **Фильтрация:** Если условие триггера истинно, контроллер приступает к генерации.
4. **Рендеринг:** Подстановка данных приложения в выбранный шаблон.
5. **Доставка:** Отправка через API выбранного сервиса.
6. **Кеширование:** Фиксация ID уведомления в аннотациях приложения для предотвращения дублей.

## Методы подписки

ArgoCD поддерживает два уровня настройки подписок:

### 1. Локальные подписки (Application level)
Настраиваются через аннотации непосредственно в манифесте `Application`. Удобно для индивидуальных настроек команд.
```yaml
annotations:
  notifications.argoproj.io/subscribe.on-sync-failed.slack: "my-channel"
```

### 2. Глобальные подписки (System level)
Настраиваются в `argocd-notifications-cm` и применяются ко всем приложениям, подходящим под селектор.
```yaml
data:
  subscriptions: |
    - recipients: [slack:alerts-channel]
      triggers: [on-sync-failed]
      selector: app=production
```

## Переменные шаблонов и логика

Внутри шаблона доступны три основных объекта:
- **`.app`**: Полный объект `Application` (metadata, spec, status).
- **`.context`**: Глобальные переменные (например, `argocdUrl`).
- **`.service`**: Параметры конкретного сервиса доставки.

### Пример сложного шаблона с логикой
```yaml
template.app-sync-status: |
  message: |
    Приложение {{.app.metadata.name}} в статусе {{.app.status.sync.status}}.
    {{ if eq .app.status.health.status "Degraded" }}
    Внимание: Обнаружены проблемы со здоровьем ресурсов!
    {{ end }}
```

## Настройка триггеров

Триггеры используют мощный механизм условий. Вы можете комбинировать статусы синхронизации и здоровья.

| Триггер | Условие (when) |
| :--- | :--- |
| **on-deployed** | `app.status.operationState.phase in ['Succeeded']` |
| **on-health-degraded** | `app.status.health.status == 'Degraded'` |
| **on-sync-running** | `app.status.operationState.phase in ['Running']` |

### Кастомный триггер в ConfigMap
```yaml
trigger.on-high-risk-change: |
  - when: app.status.sync.status == 'OutOfSync' and app.metadata.labels['criticality'] == 'high'
    send: [risk-template]
```

## Практические сценарии

### Сценарий 1: Уведомления в Telegram

**1. Настройка секрета:**
```bash
kubectl create secret generic argocd-notifications-secret \
  --from-literal=telegram-token=123456:ABC-DEF -n argocd
```

**2. Конфигурация в ConfigMap:**
```yaml
data:
  service.telegram: |
    my-bot:
      token: $telegram-token
  template.sync-failed: |
    message: "Ошибка деплоя {{.app.metadata.name}}!"
  trigger.on-sync-failed: |
    - when: app.status.operationState.phase in ['Failed', 'Error']
      send: [sync-failed]
```

### Сценарий 2: Обновление статуса в GitHub/GitLab

ArgoCD может помечать конкретный коммит галочкой или крестиком в интерфейсе Git-платформы.

```yaml
data:
  service.github: |
    appID: 123
    installationID: 456
    privateKey: $github-private-key
```

## Диагностика и отладка

Для проверки уведомлений без реального деплоя используйте CLI ArgoCD (требуются права администратора кластера).

### Тестирование шаблона
Позволяет увидеть отрендеренное сообщение в терминале:
```bash
argocd admin notifications template test <template-name> <app-name>
```

### Проверка триггера
Проверяет, сработает ли логика для конкретного приложения:
```bash
argocd admin notifications trigger run <trigger-name> <app-name>
```

### Логирование
Если уведомления не приходят, проверьте логи основного контроллера:
```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller | grep "notifications"
```

## Дополнительная информация

**Связанные документы:**
- [Обзор архитектуры ArgoCD](./argocd_overview.md)
- [Политики синхронизации](./synchronization.md)
- [GitOps: Уведомления и алертинг](../gitops_notifications.md)

**Официальная документация:**
- [ArgoCD Notifications Guide](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/)

