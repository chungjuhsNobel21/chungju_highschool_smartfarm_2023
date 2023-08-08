# chungju_highschool_smartfarm_2023
Chungju Highschool Smartfarm Project 2023 by 3rd graders  
Special Thanks to Kyle Gabriel. - Your project helped us a lot!  
https://kylegabriel.com/projects/2020/06/automated-hydroponic-system-build.html#Building_the_Hydroponic_System  
https://www.youtube.com/watch?v=nyqykZK2Ev4  

# 하드웨어 구성 및 제어
## 하드웨어 구성 요소
 1. 온습도센서 4개
 2. ESP32-CAM 1개 -> 전원 공급해 자체 구동하고 이미지 서버에 스트리밍 하도록
 3. EC센서 1개
 4. PH센서 1개
 5. 펌프 1개
 6. A, B, C통 배관 조작 장치 각각 1개씩
 7. 수위센서 1개
 8. LED strip 8개 -> 릴레이로 조작
 9. 온도 조절등(등은 아닌데 그런 장치) 4개 -> 릴레이로 조작

## hardware.py (GPIO 모듈로 하드웨어 조작)
모든 getter 함수들은 함수값 측정에 실패할 경우 FailMeasurement 예외를 raise함  
모든 setter 함수들은 상태 지정에 실패할 경우 FailSetting 예외를 raise 함  
- get_temp_and_humidity()->list[float, float] : 온도 및 습도 측정해 반환하는 함수
- get_ec()->float : EC(전기전도도) 측정해 반환하는 함수
- get_ph()->float : ph 측정해 반환하는 함수
- set_pump_state(state:str) : 펌프 작동 상태 설정하는 함수
- get_pump_state()->str : 펌프 작동 상태 반환하는 함수 ('on'/'off')
- get_water_level()->float : 3층 물통 수위 측정해 반환하는 함수
- set_light_state(level:int, state:str) : 1층 혹은 2층 LED 전원 상태를 지정하는 함수
- get_light_state()->list[str] : 1층과 2층 LED 전원 상태를 얻어오는 함수 ['on'/'off', 'on'/'off']
- set_heater_state(state:str) : 전체 히터의 상태를 지정하는 함수
- get_heater_state()->str : 히터의 상태를 반환하는 함수 ('on'/'off')
- set_min_temp(float) :
- set_on_time(datetime) '07:00:00'
-  self.on_time = datetime 
- set_off_time()
- adjust()

# 서버 호스팅 및 웹페이지
## server.py(flask 라이브러리로 서버 운영)

## webpage(html/css 스택으로 웹페이지 UI 제작)

# contributors
2023 충주고 3학년
3805 김기훈 (팀장)
(아래에 팀원들이 git을 익히는 겸 commit을 통해 각자 본인의 이름을 입력해 반영할 것)  
(참고로 Markdown에서 줄바꿈은 엔터가 아니라 스페이스 두번이다)
