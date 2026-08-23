# Совместимость версий и обновление etcd

**etcd** имеет строгую политику версионирования. Обновление в production — регламентная операция, требующая планирования и валидации. Понимание совместимости версий критично для безопасности и стабильности.

## Опредеции

| Термин | Описание |
| :--- | :--- |
| **v2 API** | Устаревший HTTP/JSON API. Полностью удален в etcd 3.7. |
| **v3 API** | Современный gRPC/Protobuf API. Стандарт с 2018 года. |
| **Rolling Upgrade** | Поэтапное обновление узлов кластера без остановки работы. |
| **Downgrade** | Откат на предыдущую версию. Требует логической миграции данных. |
| **Feature Gate** | Флаг, включающий экспериментальную функциональность. |
| **etcdutl** | Утилита для офлайн-операций. Доступна с v3.6. |
| **Compatibility Matrix** | Таблица совместимости клиентов и серверов разных версий. |

---

## Основные концепции

### v2 vs v3: практические различия

| Аспект | v2 | v3 |
| :--- | :--- | :--- |
| **Протокол** | HTTP/JSON | gRPC/Protobuf |
| **Endpoint** | `/v2/keys/...` | `/v3/...` (gRPC) |
| **Atomic increment** | Есть (`POST /keys/?atomic=true`) | Нет (только через Txn) |
| **TTL** | Устанавливается на запись | Через Lease (отдельный механизм) |
| **Watch** | Long-polling HTTP | gRPC stream |
| **Transactions** | Ограниченные (compare-and-swap) | Полноценные (cmp + success/failure) |
| **Storage** | Отдельный store | Единый MVCC-стор |

**Миграция с v2 на v3:**
```bash
# Экспорт v2 данных
etcdctl --endpoints=http://127.0.0.1:2379 export /backup/v2-backup.db

# Или через API
curl http://127.0.0.1:2379/v2/keys/?recursive=true | jq .
```

### Совместимость версий

**etcd гарантирует:**
- Клиент может быть новее сервера (на одну minor версию).
- Сервер может быть новее клиента (на одну minor версию).

| Сервер | Клиент | Работает? |
| :--- | :--- | :--- |
| 3.5.3 | 3.5.0 | Да |
| 3.5.3 | 3.6.0 | Да (совместимость) |
| 3.5.3 | 3.7.0 | Да (совместимость) |
| 3.5.3 | 3.4.0 | Нет (клиент старее) |

### Совместимость с Kubernetes

| Kubernetes | Минимальный etcd | Рекомендуемый etcd | Примечание |
| :--- | :--- | :--- | :--- |
| 1.28 | 3.5.x | 3.5.10+ | Последний patch 3.5 обязателен |
| 1.29 | 3.5.x | 3.5.10+ | 3.5.33+ рекомендуется |
| 1.30 | 3.5.x | 3.6.x | Поддержка 3.6 |
| 1.31 | 3.6.x | 3.7.x | 3.7 — текущий стандарт |
| 1.32 | 3.7.x | 3.7.1+ | Только 3.7+ |

**Важно:**
- Kubernetes не поддерживает etcd новее, чем зафиксировано в compatibility matrix.
- При обновлении K8s проверяйте release notes: иногда требуется обязательное обновление etcd перед upgrade control plane.
- kube-apiserвер проверяет версию etcd при старте и может отказаться запускаться при несовместимой версии.

**Downgrade:**
- **etcd НЕ поддерживает downgrade snapshot.** Снапшот v3.7 нельзя восстановить на v3.6.
- **Решение:** Логическая миграция через `etcdctl get --prefix --keys-only` или промежуточный кластер.

### Feature Gates (v3.5+)

Некоторые функции требуют явного включения:

| Feature Gate | Версия | Назначение |
| :--- | :--- | :--- |
| `EnableLeaseCheckpoint` | v3.4+ | Checkpoint lease TTL (уменьшает время восстановления после перезапуска) |
| `EnableGRPCGateway` | v3.5+ | REST API через gRPC-gateway |
| `WatchMultipleKeys` | v3.6+ | Оптимизация watch по префиксу |

```bash
# Включение feature gate
etcd --feature-gates=EnableLeaseCheckpoint=true ...
```

---

## Практические сценарии

### Rolling Upgrade: 3.5 → 3.7

**Алгоритм:**

1. **Подготовка:**
   - Убедиться, что все узлы на 3.5.33+ (последний патч 3.5).
   - Сделать снапшот: `etcdctl snapshot save /backup/pre-upgrade.db`.
   - Проверить валидность: `etcdutl snapshot status /backup/pre-upgrade.db`.

2. **Обновление первого узла (не лидера!):**
   ```bash
   # Передать лидерство на другой узел
   etcdctl move-leader <LEADER_ID>

   # Остановить etcd
   systemctl stop etcd

   # Обновить бинарники (apt/yum)
   apt-get update && apt-get install -y etcd=3.7.1

   # Запустить
   systemctl start etcd

   # Проверить здоровье
   etcdctl endpoint health --cluster
   ```

3. **Обновление оставшихся узлов:**
   - Повторить для каждого follower'а.
   - **Не обновлять лидера последним** — оставьте его на случай отката.

4. **Валидация:**
   ```bash
   # Проверить версию на всех узлах
   etcdctl --endpoints=https://... endpoint status -w table
   # → VERSION: 3.7.1 для всех

   # Проверить метрики
   curl -s http://localhost:2379/metrics | grep etcd_server_version_info
   ```

**Edge Cases:**
- Если после обновления лидер начинает flapping, откатитесь на предыдущую версию.
- При обновлении через `kubeadm` убедитесь, что kube-controller-manager использует совместимый client.

### Проверка совместимости

```bash
# Проверить версию сервера
etcdctl --version
# → etcdctl version: 3.7.1

# Проверить версию через API
curl -s http://localhost:2379/version
# → {"etcdserver":"3.7.1","etcdcluster":"3.7.1"}
```

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `etcdserver: request is too large` после обновления | Клиент использует старый max-request-bytes | Проверить флаг `--max-request-bytes` на новом сервере |
| `mvcc: required revision has been compacted` | Watcher несовместим с новой compaction политикой | Обновить клиентский код; увеличить `--auto-compaction-retention` |
| Лидер flapping после обновления | Проблема с clock skew или disk на новом узле | Проверить NTP, `fdatasync` latency |
| Snapshot не восстанавливается | Версия снапшота новее версии etcd | Используйте логический backup или промежуточный кластер |

---

## Best Practices

- **Всегда используйте последний patch-релиз:** 3.5.33+, 3.6.13+, 3.7.1+.
- **Обновляйте не-лидера первым:** Снижает риск потери кворума.
- **Делайте снапшот перед обновлением:** Это единственный способ отката.
- **Тестируйте в staging:** Обновление в production без staging-тестирования — антипаттерн.
- **Feature gates:** Не включайте экспериментальные флаги в production без тестирования.

---

## Edge Cases

- **Cluster ID mismatch:** При восстановлении из снапшота с другим `cluster-token` etcd отклонит подключение. Используйте `--initial-cluster-token` при `snapshot restore`.
- **Downgrade через 2 версии:** Невозможно (например, 3.7 → 3.5). Требуется промежуточный кластер.
- **etcdctl версии:** Клиент должен быть `>=` сервер (minor). Исключение: 3.0 клиент не работает с 3.1+ сервером из-за изменения gRPC протокола.
- **v2 data в 3.7:** v3.7 полностью удаляет v2 store. Если в снапшоте есть v2-данные, восстановление завершится ошибкой.

---

## См. также

* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — rolling upgrade и замену узлов.
* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — feature gates.
* **[Шпаргалка etcdctl](./etcdctl_cheatsheet.md)** — snapshot save/restore.
