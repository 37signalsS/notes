# Удаленный доступ к серверам

## Определения

* **Удаленный доступ**: Совокупность методов и технологий для управления сервером на расстоянии.
* **Внутриполосное управление (In-Band Management)**: Доступ через основную операционную систему и сетевой стек (SSH, VNC, RDP). Требует работающей ОС.
* **Внеполосное управление (Out-of-Band Management, OOB)**: Аппаратный доступ, независимый от состояния ОС (IPMI, iDRAC, iLO). Используется для восстановления зависших или выключенных серверов.
* **IPMI (Intelligent Platform Management Interface)**: Стандарт для встроенного модуля управления (**Baseboard Management Controller, BMC**), предоставляющего OOB-доступ.
* **IP-KVM (KVM-over-IP)**: Технология передачи сигналов клавиатуры, видео и мыши по IP-сети. *Не следует путать с [KVM-виртуализацией](../../Linux/Virtualization/kvm/overview.md).*
* **VNC (Virtual Network Computing)**: Протокол для графического удаленного доступа к рабочему столу (In-Band).

## Базовые концепции

### Иерархия доступа

1. **Попытка доступа по SSH:** Стандартный, быстрый и безопасный способ.
2. **Эскалация до OOB (IPMI/IP-KVM):** Если сервер не отвечает по SSH или не загружается, используется внеполосное управление.

### Возможности внеполосного управления (OOB)

Модули BMC (Dell iDRAC, HP iLO, Supermicro IPMI) являются отдельными компьютерами внутри сервера и предоставляют полный аппаратный контроль:

* **Удаленная консоль:** Полный доступ к экрану, клавиатуре и мыши, включая BIOS/UEFI.
* **Управление питанием:** Принудительное выключение, включение и перезагрузка (`Hard Reset`).
* **Мониторинг состояния:** Отслеживание аппаратных датчиков.
* **Виртуальные носители (Virtual Media):** Удаленное подключение `.iso` образов для установки ОС.

### Аспекты безопасности

* **Безопасность OOB:** Интерфейсы IPMI/iDRAC/iLO должны находиться в выделенной, изолированной сети управления. Публичный доступ к ним является серьезной угрозой.
* **Безопасность VNC:** Протокол VNC по умолчанию не шифрует трафик. VNC **всегда** должен туннелироваться через SSH.

## Практические сценарии

### Сценарий 1: Стандартный доступ по SSH

Основной протокол для безопасного удаленного управления. Подробнее: **[SSH (Secure Shell)](../Security/ssh/ssh_overview.md)**.

### Сценарий 2: Аварийный доступ через IPMI/iDRAC/iLO

1. Подключитесь к веб-интерфейсу или CLI модуля управления (iDRAC).
2. Запустите удаленную консоль (Remote Console / Virtual KVM).
3. Проанализируйте вывод на экране (например, `Kernel Panic`).
4. При необходимости выполните принудительную перезагрузку.
5. Для переустановки ОС подключите `.iso` образ через `Virtual Media`.

### Сценарий 3: Настройка VNC с SSH-туннелем

**1. Установка окружения и VNC-сервера:**

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install xfce4 xfce4-goodies tigervnc-standalone-server -y
```

**2. Первоначальная настройка VNC:**
Запустите `vncserver` для создания конфига и задания пароля, затем остановите временный сеанс.

```bash
vncserver
vncserver -kill :1
```

**3. Конфигурация VNC для запуска XFCE:**

```bash
echo -e '#!/bin/bash\nxrdb $HOME/.Xresources\nstartxfce4 &' > ~/.vnc/xstartup
chmod +x ~/.vnc/xstartup
```

**4. Создание службы Systemd для автозапуска:**
Создайте `/etc/systemd/system/vncserver@.service`, заменив `YOUR_USERNAME` на ваше имя пользователя.

```bash
sudo tee /etc/systemd/system/vncserver@.service > /dev/null <<EOF
[Unit]
Description=Start TigerVNC server at startup
After=syslog.target network.target

[Service]
Type=forking
User=YOUR_USERNAME
Group=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME

PIDFile=/home/YOUR_USERNAME/.vnc/%H:%i.pid
ExecStartPre=-/usr/bin/vncserver -kill :%i > /dev/null 2>&1
ExecStart=/usr/bin/vncserver -depth 24 -geometry 1280x800 -localhost :%i
ExecStop=/usr/bin/vncserver -kill :%i

[Install]
WantedBy=multi-user.target
EOF
```

> Опция `-localhost` в `ExecStart` заставляет VNC-сервер принимать подключения только с `localhost`, запрещая прямой доступ извне.

**5. Управление службой VNC:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable vncserver@1.service
sudo systemctl start vncserver@1.service
sudo systemctl status vncserver@1.service
```

**6. Подключение через SSH-туннель:**
С локального компьютера перенаправьте удаленный порт `5901` на локальный `59001`:

```bash
ssh -L 59001:localhost:5901 -N -f -l your_username your_server_ip
```

Подключитесь VNC-клиентом к `localhost:59001`.

## Дополнительная информация

### Сравнение IPMI и внешнего IP-KVM

| Возможность | IPMI / BMC (встроенное) | Внешний IP-KVM |
| :--- | :---: | :---: |
| **Удаленная консоль (KVM)** | ✅ | ✅ |
| **Управление питанием** | ✅ | ❌ |
| **Монтирование образов (.iso)** | ✅ | ❌ |
| **Мониторинг датчиков** | ✅ | ❌ |

Ключевое различие: IPMI — это комплексная система управления, IP-KVM — только доступ к консоли.

### Проприетарные реализации IPMI/BMC

* **Dell:** **iDRAC** (integrated Dell Remote Access Controller)
* **HP:** **iLO** (Integrated Lights-Out)
* **Lenovo/IBM:** **IMM** (Integrated Management Module)
* **Cisco:** **CIMC** (Cisco Integrated Management Controller)
* **Supermicro:** **IPMI** (стандартная спецификация)

### Последовательный консольный сервер (Serial Console Server)

Альтернативный метод OOB для оборудования с последовательным портом (COM). Администратор подключается по SSH к консольному серверу, а с него получает текстовый доступ к консоли устройства. Часто используется для сетевого оборудования.
