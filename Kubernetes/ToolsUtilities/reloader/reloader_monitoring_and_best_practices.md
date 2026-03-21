# Reloader — Мониторинг и лучшие практики

## 1. Мониторинг и отладка

### Просмотр логов Reloader

```bash
kubectl logs -f deployment/reloader -n monitoring
```

### Пример вывода логов

```
time="2025-01-15T10:30:45Z" level=info msg="Reloader started"
time="2025-01-15T10:30:46Z" level=info msg="Watching for changes in namespace: default"
time="2025-01-15T10:31:00Z" level=info msg="ConfigMap 'openresty-index-html' updated in namespace 'default'"
time="2025-01-15T10:31:01Z" level=info msg="Triggering rolling upgrade for Deployment 'openresty-deployment'"
```

### Проверка статуса

```bash
kubectl get deployment reloader -n monitoring
kubectl describe deployment reloader -n monitoring
```

---

## 2. Лучшие практики

1. **Игнорируйте системные namespace'ы** — `kube-system`, `kube-public`, `kube-node-lease`
2. **Используйте явные аннотации** — предсказуемее чем `auto: "true"`
3. **Настройте мониторинг** — отслеживайте логи Reloader
4. **Тестируйте в staging** — перед применением в production
5. **Задавайте ресурсы** — limits и requests для контроллера

---

## 3. Сравнение с альтернативами

| Инструмент | Подход | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Reloader** | Аннотации | Простота, гибкость | Требует аннотаций |
| **Checksum-аннотация** | Хеш в манифесте | Работает без контроллера | Требует настройки CI/CD |
| **ArgoCD** | GitOps | Полный контроль | Сложнее в настройке |

**Подробнее:** [Обновление ConfigMap и его влияние на поды](../../Base/ConfigMap/update_and_rollout.md)

---

## 4. Ограничения

- **Не работает с `subPath` по умолчанию** — требуется явная аннотация
- **Только rolling restart** — не обновляет поды in-place
- **Один контроллер на кластер** — может быть bottleneck в больших кластерах

---

## 5. Связанные документы

- **[Обзор и концепции](./reloader_overview.md)** — базовые определения
- **[Установка Reloader](./reloader_installation.md)** — установка через Helm и манифесты
- **[Сценарии использования](./reloader_usage_scenarios.md)** — практические примеры
- **[ConfigMap](../../Base/ConfigMap/update_and_rollout.md)** — обновление ConfigMap и rollout
- **[Secrets](../../Security/application_secrets_management.md)** — управление секретами
- **[Deployment](./index.md)** — rolling update стратегия

### Репозиторий и документация

- [GitHub: stakater/Reloader](https://github.com/stakater/Reloader)
- [Документация Stakater](https://github.com/stakater/Reloader#readme)
- [Helm Chart](https://github.com/stakater/stakater-charts/tree/master/charts/reloader)
