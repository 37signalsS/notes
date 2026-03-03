# Wireshark: Использование tshark (командная строка)

## Использование `tshark` (командная строка)

`tshark` идеально подходит для автоматизации и работы в средах без GUI.

* **Установка (если не установлен с Wireshark)**: `sudo apt install tshark` (Debian/Ubuntu) или `sudo dnf install wireshark-cli` (Fedora/RHEL).

```bash
# Показать список доступных интерфейсов
tshark -D

# Захват 100 пакетов с интерфейса enp0s3 и сохранение в файл
sudo tshark -i enp0s3 -c 100 -w capture.pcapng

# Чтение из файла с применением фильтра отображения
tshark -r capture.pcapng -Y "ip.addr == 185.15.59.224"

# Захват трафика по HTTP (порт 80) с использованием фильтра захвата
sudo tshark -i enp0s3 -f "tcp port 80"

# Экспорт определенных полей в CSV
tshark -r capture.pcapng -T fields -e ip.src -e ip.dst -e frame.len -E header=y -E separator=, > packets.csv

# Экспорт в JSON (для дальнейшей обработки)
tshark -r capture.pcapng -T json > packets.json

# Статистика по диалогам (conversations)
tshark -r capture.pcapng -q -z conv,ip

# Статистика по протоколам
tshark -r capture.pcapng -q -z io,phs

# Дешифрование TLS с использованием keylog файла
tshark -r capture.pcapng -o tls.keylog_file:/path/to/keys.log
```
