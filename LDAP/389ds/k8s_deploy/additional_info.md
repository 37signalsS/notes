# 389DS в Kubernetes: Дополнительная информация

## Troubleshooting

| Проблема | Решение |
| :--- | :--- |
| Pod не запускается | Проверить логи: `kubectl logs 389ds-0 -n ldap` |
| PVC не создаётся | Проверить StorageClass: `kubectl get sc` |
| Репликация не работает | Проверить сеть между подами, DNS |

## Мониторинг

```bash
# Статус подов
kubectl get pods -l app=389ds -n ldap

# Проверка репликации
kubectl exec 389ds-0 -n ldap -- \
  dsconf replication status --suffix "dc=example,dc=com" me-to-389ds-1

# Логи
kubectl logs -f 389ds-0 -n ldap
```

## Best Practices

1. **Anti-affinity** — распределять поды по разным узлам
2. **Resource limits** — ограничивать CPU/RAM для предсказуемости
3. **Backup** — использовать `dsctl backup` перед обновлениями
4. **Update strategy** — обновлять по одному поду (RollingUpdate)
5. **Monitoring** — отслеживать статус репликации и свободное место

## Диаграмма потока инициализации

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Job       │────▶│  StatefulSet │────▶│   Service   │
│  (init)     │     │   (389DS)    │     │ (LoadBalancer)│
└─────────────┘     └──────────────┘     └─────────────┘
       │                    │                    │
       ▼                    ▼                    ▼
  - Проверка           - Запуск подов     - Внешний доступ
  - Backend            - PVC              - LDAP/LDAPS
  - Репликация         - ConfigMap        - DNS
  - DIT                - Secret
  - Плагины
```

## Связанные темы

* [Docker развёртывание](./docker.md)
* [Настройка репликации](./replication.md)
* [Плагины](./plugins.md)
* [OpenLDAP в Kubernetes](../openldap_kubernetes.md)

---

## Связанные документы

* **[Определения](./definitions.md)** — базовые термины
* **[Основные концепции](./basic_concepts.md)** — архитектура развёртывания, требования
* **[Практические сценарии](./practical_scenarios.md)** — StatefulSet, сервисы, инициализация

---

*Этот файл является частью декомпозированной документации. Исходный файл: [kubernetes.md](../kubernetes.md)*
