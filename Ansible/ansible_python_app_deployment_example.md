# Ansible: Пример развертывания Python-приложения

Этот документ демонстрирует, как использовать Ansible для автоматизации развертывания Python-приложения, включая настройку виртуального окружения (`venv`) и создание `systemd` юнита для управления сервисом.

---

## 1. Подготовка и запуск

1.  **Скопируйте материалы:** Убедитесь, что все необходимые файлы (плейбук, файлы приложения, шаблоны) находятся в рабочей директории на `controlnode`.
2.  **Запустите плейбук:**
    ```bash
    ansible-playbook playbook.yml
    ```

## 2. Анализ плейбука

Ниже представлен пример плейбука для развертывания Python-приложения на сервере с CentOS.

```yaml
- name: "Pip venv"
  hosts: "centos_python"
  become: true # Задачи будут выполняться с повышением привилегий
  vars:
    app_name: "hello"
    mysql_password: "password"
    ansible_python_interpreter: /usr/bin/python3
  tasks:
    - name: "Copy python files"
      ansible.builtin.copy:
        src: files/app
        dest: /apps/{{ app_name }}
        owner: vagrant
        group: vagrant
        mode: 0644

    - name: Install virtualenv via pip
      pip:
        name: virtualenv
        executable: pip3

    - name: Install requirements into virtualenv
      pip:
        requirements: /apps/{{ app_name }}/app/requirements.txt
        virtualenv: /apps/{{ app_name }}/venv
        virtualenv_command: /usr/bin/python3 -m venv

    - name: Copy service file
      ansible.builtin.template:
        src: service.service.j2
        dest: /etc/systemd/system/{{ app_name }}.service
        owner: vagrant
        group: vagrant
        mode: 0644
      notify: Reload systemd # Уведомление для обработчика

    # ... другие задачи, например, настройка БД
```

### Ключевые моменты плейбука:

*   `ansible_python_interpreter: /usr/bin/python3`: Явно указывает Ansible использовать `python3` для выполнения модулей на целевом хосте. Это критически важно для систем, где по умолчанию используется Python 2.
*   **`ansible.builtin.copy`**: Копирует файлы приложения на удаленный хост.
*   **`pip: name=virtualenv`**: Устанавливает пакет `virtualenv` глобально с помощью `pip3`.
*   **`pip: requirements=...`**: Устанавливает зависимости из файла `requirements.txt` в указанное виртуальное окружение.
    *   `virtualenv: /apps/{{ app_name }}/venv`: Путь, где будет создано или использовано виртуальное окружение.
    *   `virtualenv_command: /usr/bin/python3 -m venv`: Явно указывает команду для создания `venv`, что помогает избежать проблем с версиями.
*   **`ansible.builtin.template`**: Создает `systemd` юнит из шаблона `service.service.j2`, позволяя динамически подставлять переменные (например, `app_name`).
*   **`notify: Reload systemd`**: Отправляет уведомление обработчику `Reload systemd` (который должен содержать задачу `systemd: daemon_reload: yes`), чтобы `systemd` узнал о новом юните.

## 3. Проверка результата

После успешного выполнения плейбука:
*   **PLAY RECAP** покажет статистику выполнения.
*   Вы можете проверить доступность развернутого сервиса, открыв в браузере его адрес, например: `http://192.168.51.2`.
