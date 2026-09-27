# Диагностика проблем с низкой энтропией в Linux

## Определения

**Энтропия (Entropy)** — уровень непредсказуемости и случайности данных, используемый ядром Linux для генерации криптографически стойких последовательностей. Критически важна для TLS-рукопожатий, генерации ключей и сессионных токенов.

**`/dev/random`** — символьное устройство. В старых ядрах (< 5.6) блокировалось при истощении пула энтропии. В современных ядрах блокируется только на раннем этапе загрузки (до инициализации генератора).

**`/dev/urandom`** — неблокирующее устройство. Использует криптографический генератор (CSPRNG, обычно ChaCha20), который периодически обновляется из пула энтропии ядра.

**`getrandom()` (syscall)** — системный вызов, предоставляющий криптографически случайные байты. При вызове с флагом `GRND_RANDOM` требует неистощённый пул энтропии (аналогично `/dev/random`). Без флага возвращает данные немедленно после инициализации CSPRNG.

**VirtIO RNG** — технология проброса аппаратной энтропии с хоста в гостевую виртуальную машину (KVM/QEMU), предотвращающая «голодание» энтропии в виртуализированных средах.

**HAVEGE (HArdware Volatile Entropy Gathering and Expansion)** — алгоритм сбора энтропии на основе высокоточных измерений временных задержек (jit) между исполнением инструкций CPU.

**CRNG (Cryptographic Random Number Generator)** — криптографический генератор случайных чисел ядра. Инициализируется при загрузке (`crng init done` в journalctl).

**`entropy_avail`** — файл в `/proc/sys/kernel/random/`, отображающий текущий объём доступной энтропии в пуле (в битах).

**Hardware RNG (hRNG)** — аппаратный генератор случайных чисел на основе физических процессов (тепловой шум, фотонный шум, RDRAND, TPM).

---

## Основные концепции

### Механизм и симптомы проблемы

В виртуальных машинах (ВМ) и изолированных контейнерах ядро часто не получает достаточно «шума» от прерываний (нет физической клавиатуры, мыши, предсказуемый ввод-вывод). Это приводит к истощению пула энтропии.

**Типичные симптомы:**
- Задержки при установке **SSH-соединений** (2-10 секунд до приглашения пароля).
- Зависания при генерации **GPG/SSL ключей**.
- Медленный старт **Java-приложений** (из-за инициализации `SecureRandom`).
- Таймауты при выполнении **TLS-рукопожатий** в высоконагруженных веб-серверах.

### Жизненный цикл пула энтропии

**Пул энтропии ядра** — буфер фиксированного размера (по умолчанию 4096 бит в ядрах до 5.10, 256 бит в 5.10+), куда добавляется «шум» из аппаратных источников и откуда он забирается при запросах случайных чисел.

**Этапы инициализации:**
1. **Ранняя загрузка (early boot):** entropy = 0. `/dev/random` блокируется, `/dev/urandom` возвращает небезопасные данные.
2. **Сбор шума:** ядро накапливает энтропию от таймеров, прерываний, датчиков.
3. **`crng init done`:** после накопления порогового объёма (обычно 64 бита) CSPRNG инициализируется. С этого момента `/dev/urandom` и `/getrandom()` без `GRND_RANDOM` возвращают безопасные данные.
4. **Работа:** пул пополняется фоновыми задачами (e.g., `random/block` worker).

**Минимальные пороги для операций:**
- **TLS-рукопожатие:** 64–128 бит (одноразовый отпечаток)
- **GPG-ключ (2048 бит RSA):** ~256 бит (для seed)
- **Долгоживущий ключ:** 256+ бит (AES-256)
- **Sessions tokens (JWT, session cookie):** 128–256 бит

### Источники энтропии

| Источник | Описание | Доступность |
|----------|----------|-------------|
| **Прерывания CPU (IRQ)** | Таймеры, сетевые карты, диски | Всегда |
| **RDRAND** | Инструкция x86 (Ivy Bridge+), ~2 Gbps | Intel CPUs |
| **RNDR** | Инструкция ARMv8.5-A+ | ARM CPUs |
| **TPM** | Trusted Platform Module, ~20–50 Mbps | Серверы/ноутбуки |
| **VirtIO RNG** | Проброс с хоста в ВМ | KVM/QEMU, Virtuozzo |
| **HAVEGE** | Jitter CPU таймеров | Программный |
| **Bootloader seed** | UEFI EFI_RNG_PROTOCOL | Современные загрузчики |

### Эволюция в ядрах 5.6+

Начиная с ядра 5.6, поведение `/dev/random` и `/dev/urandom` было унифицировано. Оба устройства используют один и тот же CSPRNG.
- Если генератор инициализирован (собрано достаточно «шума» при загрузке), `/dev/random` **больше не блокируется**.
- Если система «висит» в ожидании энтропии на современном ядре, проблема обычно локализована на самом раннем этапе загрузки (`crng init done`).

---

## Практические сценарии

### 1. Диагностика пула энтропии

**Проверка текущего уровня:**
```bash
cat /proc/sys/kernel/random/entropy_avail
# → 256 (Норма для ядер 5.10+; ранее норма была 3000-4000)
```
*Примечание:* В ядрах 5.10+ размер пула по умолчанию уменьшен до 256 бит, и это считается достаточным.

**Мониторинг при нагрузке:**
```bash
watch -n1 cat /proc/sys/kernel/random/entropy_avail
```
Если значение падает до 0 при попытке соединения по SSH — энтропии не хватает.

**Трассировка блокировок (getrandom):**
```bash
sudo strace -T -e getrandom,read -p <PID>
# → getrandom(..., 0) = 16 <0.000042> (Быстрый ответ)
# → getrandom(..., 0) ... <unfinished ...> (Блокировка)
```

---

### 2. Решение для физических серверов и ВМ (haveged)

`haveged` использует алгоритм HAVEGE для сбора энтропии на основе тонких колебаний таймеров CPU (Jitter).

```bash
# Установка и запуск
sudo apt install haveged -y
sudo systemctl enable --now haveged

# Проверка статуса
systemctl status haveged
# → active (running) since ...
```

---

### 3. Решение для KVM/QEMU (VirtIO RNG)

Наиболее эффективный способ в виртуализированных средах — передать энтропию с хоста.

1. **На стороне хоста (libvirt):** добавьте устройство в XML конфиг ВМ:
```xml
<devices>
  <rng model='virtio'>
    <backend model='random'>/dev/urandom</backend>
  </rng>
</devices>
```
2. **Внутри ВМ:** ядро автоматически увидит устройство `hwrng`.
```bash
cat /sys/class/misc/hw_random/rng_available
# → virtio
```
3. **Проверка работы:**
```bash
sudo rngd -v
# → Available entropy sources: virtio
sudo cat /proc/sys/kernel/random/entropy_avail
# → Значение должно расти
```

---

### 4. Использование rng-tools

Утилиты для подпитки пула энтропии из аппаратных источников (TPM, RDRAND инструкции CPU).

```bash
sudo apt install rng-tools5 -y
sudo systemctl enable --now rng-tools
```

**Для TPM:**
```bash
# Проверка доступности TPM
cat /sys/class/misc/hw_random/rng_available
# → tpm-rng

# Запуск rngd с явным указанием TPM
sudo rngd -r /dev/hwrng -o /dev/random -f
```

---

### 5. Блокировка при загрузке (Early Boot CRNG)

**Симптом:** Система зависает на早期 этапе загрузки с сообщением `crng init done` или медленная загрузка.

**Диагностика:**
```bash
journalctl -b | grep -i "crng\|random\|entropy"
# → random: crng init done
# → random: 2 urandom warning(s) missed due to ratelimiting
```

**Решение:**
1. **Добавить bootloader seed** (GRUB/systemd-boot через UEFI):
   ```bash
   # Проверка наличия EFI seed
   dmesg | grep -i "efi.*rng\|seed"
   # → [0.000000] efi: rng seed
   ```
2. **Резервное решение:** haveged с ранним стартом:
   ```bash
   sudo systemctl enable haveged
   # Проверка раннего старта
   systemctl show haveged -p ExecMainStartTimestamp
   ```
3. **Для виртуальных машин:** убедиться, что `virtio-rng` подключён.

---

### 6. Контейнеры Docker/LXC

**Проблема:** Контейнеры разделяют ядро хоста и видят ограниченную энтропию (`entropy_avail` показывает значение хоста, но не имеют прямого доступа к устройствам).

**Диагностика внутри контейнера:**
```bash
docker exec <container> cat /proc/sys/kernel/random/entropy_avail
# → 0 или низкое значение
```

**Решение:**
1. **На хосте:** установить `haveged` или подключить `virtio-rng`.
2. **Для Docker:** пробросить устройство:
   ```bash
   docker run --device=/dev/random --device=/dev/urandom ...
   ```
3. **В Docker Compose:**
   ```yaml
   services:
     app:
       devices:
         - /dev/random:/dev/random
         - /dev/urandom:/dev/urandom
   ```

---

### 7. Физические серверы без аппаратного RNG

**Симптом:** `entropy_avail` редко поднимается выше 100–200 бит, даже при нагрузке.

**Диагностика:**
```bash
cat /proc/sys/kernel/random/entropy_avail
watch -n1 cat /proc/sys/kernel/random/entropy_avail
# Медленный рост или стагнация
```

**Решение:**
1. **Установить haveged:**
   ```bash
   sudo apt install haveged -y
   sudo systemctl enable --now haveged
   ```
2. **Проверить наличие RDRAND:**
   ```bash
   grep -o rdrand /proc/cpuinfo | wc -l
   # → 0 (нет поддержки) или >0 (есть поддержка)
   ```
3. **Альтернатива:** `rng-tools` с поддержкой TPM (если есть модуль).

---

### 8. Мониторинг энтропии в production

**Автоматический мониторинг через systemd:**
```bash
# Создание unit-файла
cat << 'EOF' | sudo tee /etc/systemd/system/entropy-monitor.service
[Unit]
Description=Entropy Pool Monitor
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'echo "entropy_avail=$(cat /proc/sys/kernel/random/entropy_avail)" | systemd-cat -t entropy-monitor -p info'
EOF
```

**Мониторинг через cron:**
```bash
# /etc/cron.d/entropy-monitor
*/5 * * * * root test $(cat /proc/sys/kernel/random/entropy_avail) -lt 100 && echo "LOW ENTROPY" | mail -s "Alert" admin@example.com
```

**Метрики Prometheus:**
```bash
# node_exporter собирает метрику node_entropy_available
curl http://localhost:9100/metrics | grep entropy
# → node_entropy_available 256
```

---

### 9. Блокировка SSH и GPG при генерации ключей

**Симптом:** `ssh-keygen` или `gpg --gen-key` зависает на несколько секунд или минут.

**Диагностика:**
```bash
# Проверка блокировки getrandom
sudo strace -T -e getrandom -p $(pgrep ssh-keygen)
# → getrandom(..., GRND_RANDOM) ... <unfinished ...>

# Проверка доступной энтропии
cat /proc/sys/kernel/random/entropy_avail
# → 15 (низкое значение)
```

**Решение:**
1. **Временное:** подключить haveged.
2. **Постоянное:** использовать `virtio-rng` или TPM.
3. **Для one-time операций:** `cat /dev/urandom | sudo tee /dev/random` (не рекомендуется для production).

**Предотвращение:**
```bash
# Для ssh-keygen
ssh-keygen -t ed25519 -a 100
# Использует алгоритм Ed25519, менее чувствительный к энтропии

# Для GPG
gpg --gen-key --batch
# В batch-режиме можно предварительно накопить энтропию
```

---

### 10. Пакетные операции и reprepro/GPG

**Симптом:** `reprepro` или `debsign` зависает при подписании пакетов.

**Диагностика:**
```bash
# Проверка ошибки
reprepro ... 2>&1 | grep -i "entropy\|random\|key"
# → Not enough entropy

# Проверка в реальном времени
sudo dmesg -w
# → random: nonblocking pool is initialized
```

**Решение:**
1. **Убедиться, что haveged запущен:**
   ```bash
   systemctl status haveged
   sudo systemctl enable --now haveged
   ```
2. **Предварительное накопление энтропии:**
   ```bash
   # Запустить фоновый процесс накопления
   sudo rngd -r /dev/urandom -o /dev/random -f &
   ```
3. **Для batch-обработки:** запускать в screen/tmux с включённым haveged.

---

---

## Дополнительная информация

### Типичные проблемы и решения

| Проблема | Симптомы | Причина | Решение |
|----------|----------|---------|---------|
| `entropy_avail` = 0 | SSH, GPG, TLS зависают | Нет аппаратного RNG, ВМ без VirtIO | haveged / virtio-rng |
| `getrandom` блокируется | strace показывает `<unfinished ...>` | Неинициализированный CRNG (early boot) | Подождать `crng init done`, добавить bootloader seed |
| `Not enough entropy` в reprepro | Подпись пакетов зависает | Нет haveged/rng-tools | Установить и запустить haveged |
| Медленный старт Java | Приложение «виснет» на старте | SecureRandom блокируется | haveged, JVM `-Djava.security.egd=file:/dev/urandom` |
| Контейнер без энтропии | Приложения в Docker зависают | Контейнеры не имеют доступа к /dev/random | Пробросить устройства на хосте |
| RDRAND не работает | rng-tools не видит источник | Устаревшее ядро или CPU без поддержки | Проверить `/proc/cpuinfo`, обновить ядро |

### Чек-лист быстрой проверки

1. **Проверка уровня энтропии:**
   ```bash
   cat /proc/sys/kernel/random/entropy_avail
   ```
   - Норма: > 128 (ядро 5.10+), > 1000 (ядро < 5.10)

2. **Проверка инициализации CRNG:**
   ```bash
   journalctl -b | grep -i "crng init done"
   # Должно присутствовать в выводе
   ```

3. **Проверка работающих демонов:**
   ```bash
   systemctl is-active haveged rng-tools
   # Оба должны быть active
   ```

4. **Проверка аппаратных источников:**
   ```bash
   cat /sys/class/misc/hw_random/rng_available
   # Должен содержать: virtio, tpm-rng, rdrand и т.д.
   ```

5. **Проверка блокировок getrandom:**
   ```bash
   sudo strace -T -e getrandom -p <PID> 2>&1 | grep -c "unfinished"
   # Должно быть 0
   ```

### Рекомендации

1. **Всегда используйте `/dev/urandom`** или `getrandom()` без `GRND_RANDOM`. Для 99.9% задач (включая генерацию долгоживущих ключей) это криптографически безопасно.
2. **Для виртуальных машин** используйте `virtio-rng` — это наиболее эффективное решение.
3. **Для физических серверов** без TPM/RDRAND установите `haveged`.
4. **Не используйте `/dev/random`** в production коде — это может привести к зависаниям.
5. **Мониторьте `entropy_avail`** в production через Prometheus (`node_exporter`) или cron.
6. **В Docker/Kubernetes** пробрасывайте `/dev/urandom` и `/dev/random` в контейнеры, если приложения используют криптографию.
7. **Для Java-приложений** добавьте JVM-параметр `-Djava.security.egd=file:/dev/urandom`.
8. **Перед генерацией GPG-ключей** убедитесь, что haveged запущен минимум 5 минут.

### Очистка

После завершения диагностики:
1. **Остановить фоновые процессы rngd** (если запускались вручную):
   ```bash
   sudo pkill rngd
   ```
2. **Откатить изменения в libvirt XML** (если тестировали VirtIO RNG):
   ```bash
   virsh edit <vm-name>
   # Удалить секцию <rng> из конфигурации
   ```
3. **Удалить временные unit-файлы systemd:**
   ```bash
   sudo systemctl disable --now entropy-monitor
   sudo rm /etc/systemd/system/entropy-monitor.service
   ```
4. **Удалить временные ключи** (если генерировали для тестов):
   ```bash
   rm -rf ~/.gnupg/private-keys-v1.d/*
   gpg --delete-secret-keys <key-id>
   ```
5. **В Docker Compose** удалить проброшенные устройства из конфигурации после тестирования.

### См. также

- [**Файловая система /dev**](../../FileSystems/virtual_fs_dev.md) — обзор символьных устройств.
- [**Диагностика производительности**](./linux_performance_diagnostics_case.md) — кейс №5 (зависания при крипто-операциях).
- [**Харденинг ядра Linux**](../../Security/Mechanisms/Kernel/hardening.md) — использование RDRAND и RDSEED.
