# Upgrade IOS on CISCO ASR901
version 06.10.2020

скрипт для:
- удаления старых образов IOS с CSG
- squeeze
- копирование новых образов

arguments:

- **del**: delete old IOS, except 15.4(3)S4 and 15.6(2)SP7
- **squeeze**: squeeze flash:
- **copy**: copy 15.6(2)SP7, set boot, check MD5
- **del4**: delete 15.4(3)S4 if current IOS is 15.6(2)SP7
- **all**: del, squeeze, copy, except del4


- список всех IOS
- проверить SFP на UPLINK, вендор Cisco ?
- удалить старые IOS, показать какие остались
- squeeze
- SFP если не Cisco запрятить обновление
- проверить есть ли IOS в Flash
    - если нет проверить Free Space
    - скопировать
- проверить на MD5
