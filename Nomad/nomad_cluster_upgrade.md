# Nomad — Обновление кластера (Cluster Upgrade)

## Определения

**Rolling Upgrade** — последовательное обновление узлов Nomad без простоя сервиса, при котором каждый узел обновляется и возвращается в кластер перед обновлением следующего.

**Raft Snapshot** — снимок состояния кластера (джобы, аллокации, ACL), создаваемый перед обновлением для возможности отката.

**Upgrade Version Strategy** — политика обновления: сначала серверы, затем клиенты, с проверкой совместимости версий.

## Основные концепции

### Совместимость версий

| Компонент | Правило |
| :--- | :--- |
| **Серверы** | Серверы должны быть на одной версии (лидер определяет API version) |
| **Клиенты** | Клиенты могут отставать на 1 major version от серверов |
| **Драйверы задач** | Драйверы должны быть совместимы с версией клиента |

**Порядок обновления:**
1. Серверы (по одному, с проверкой кворума)
2. Клиенты (по одному, с drain)
3. Драйверы задач (если требуется)

### Подготовка к обновлению

```bash
# 1. Проверка текущей версии
nomad version

# 2. Проверка статуса кластера
nomad server members
nomad node status

# 3. Создание снапшота Raft
nomad operator raft snapshot save /backup/nomad-pre-upgrade-$(date +%Y%m%d).snap

# 4. Проверка доступных обновлений
curl -s https://releases.hashicorp.com/nomad/ | grep nomad
```

## Практические сценарии

### Сценарий 1: Обновление серверов (3 ноды)

```bash
# Порядок: каждая нода последовательно
# Нода 1 (не лидер):
nomad node drain -enable -self -deadline="10m"
sudo systemctl stop nomad
sudo /usr/local/bin/nomad agent -config=/etc/nomad.d/ &
sleep 30
nomad node drain -disable -self
nomad node eligibility -enable -self

# Нода 2 (не лидер):
# ... повторить процедуру

# Нода 3 (лидер — последняя):
# Сначала проверить, что первые 2 ноды обновлены и healthy
nomad server members
# Затем обновить лидера
```

**Проверка после обновления каждой ноды:**
```bash
# Проверка версии
nomad version

# Проверка статуса
nomad server members
# → Все ноды в состоянии "alive"

# Проверка кворума
nomad operator raft list-parsers
# → Лидер определён
```

### Сценарий 2: Обновление клиентов с Drain

```bash
# 1. Drain клиента
nomad node drain -enable <node-id> -deadline="15m"

# 2. Ожидание завершения аллокаций
watch nomad node status <node-id>
# → Status: drain, Allocations: 0

# 3. Обновление Nomad
sudo systemctl stop nomad
sudo /usr/local/bin/nomad agent -config=/etc/nomad.d/ &

# 4. Снятие drain
nomad node drain -disable <node-id>
nomad node eligibility -enable <node-id>

# 5. Проверка
nomad node status <node-id>
# → Status: ready, Eligibility: eligible
```

### Сценарий 3: Автоматизация обновления через Ansible

```yaml
- name: Upgrade Nomad on server
  hosts: nomad_servers
  serial: 1  # По одному узлу
  tasks:
    - name: Create Raft snapshot
      command: nomad operator raft snapshot save /backup/nomad-pre-upgrade-{{ ansible_date_time.date }}.snap
      delegate_to: localhost

    - name: Drain node
      command: nomad node drain -enable -self -deadline="10m"
      delegate_to: "{{ inventory_hostname }}"

    - name: Wait for allocations to stop
      pause:
        seconds: 60

    - name: Stop Nomad
      systemd:
        name: nomad
        state: stopped

    - name: Update Nomad binary
      copy:
        src: "nomad_{{ new_version }}_linux_amd64.zip"
        dest: /tmp/nomad.zip

    - name: Install new binary
      unarchive:
        src: /tmp/nomad.zip
        dest: /usr/local/bin/
        remote_src: yes

    - name: Start Nomad
      systemd:
        name: nomad
        state: started
        daemon_reload: yes

    - name: Wait for Nomad to start
      pause:
        seconds: 30

    - name: Disable drain
      command: nomad node drain -disable -self
      delegate_to: "{{ inventory_hostname }}"

    - name: Enable eligibility
      command: nomad node eligibility -enable -self
      delegate_to: "{{ inventory_hostname }}"
```

### Сценарий 4: Откат при неудачном обновлении

```bash
# 1. Восстановление из снапшота
# Остановить ВСЕ серверы
sudo systemctl stop nomad

# Восстановить состояние
nomad operator raft snapshot restore /backup/nomad-pre-upgrade-YYYYMMDD.snap

# Запустить серверы со старой версией
sudo systemctl start nomad

# 2. Проверка
nomad status
nomad server members
nomad acl token list
```

### Сценарий 5: Обновление с проверкой совместимости

**Проверка перед обновлением:**
```bash
# Проверка текущей версии серверов
nomad server members -verbose | grep version

# Проверка текущей версии клиентов
nomad node status -verbose | grep version

# Проверка версий драйверов
nomad node status -stats <node-id> | grep driver
```

**Рекомендации:**
- Не обновляйте больше одной серверной ноды за раз.
- Между обновлениями нод делайте паузу 5-10 минут.
- Проверяйте кворум после каждого обновления.
- Обновляйте клиенты по одному, используя drain.

## Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `leadership lost` | Недостаточно серверов для кворума | Обновляйте по одному, проверяйте кворум |
| `version mismatch` | Серверы на разных версиях | Обновите все серверы до одной версии |
| `drain stuck` | System jobs блокируют drain | Используйте `-ignore-system-jobs` |
| `restore failed` | Серверы не остановлены | Остановите все серверы перед восстановлением |

## Дополнительная информация

- [Nomad — резервное копирование](./practical_scenarios.md#15-резервное-копирование-и-восстановление) — Raft snapshots.
- [Nomad — диагностика](./practical_scenarios.md#диагностика-и-устранение-неисправностей) — CLI-команды.
- [Ansible: Patch Management](../Ansible/ansible_patch_management.md) — автоматизация обновлений.
