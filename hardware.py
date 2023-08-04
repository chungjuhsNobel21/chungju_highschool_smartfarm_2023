import RPI.GPIO as GPIO
import Adafruit_DHT
import time
import board
import busio
import adafruit_mcp3xxx.mcp3008 as MCP
from adafruit_mcp3xxx.analog_in import AnalogIn
import RPi.GPIO as GPIO

# 핀 배치들을 변수로 저장해둠
pin_led_first_floor = 1
pin_led_second_floor = 2
pin_heater = 3
pin_pump = 4
pin_water_level_sensor = 5
pin_ph_sensor = 6


# pip install Adafruit_DHT로 DHT 온습도센서 사용 모듈을 설치


# 스마트팜 하드웨어와 소통하는 클래스를 정의
class smartFarm_Device:
    
    def __init__(self):
        '''클래스 초기화'''
        self.start_device()
            

    def start_device(self):
        '''모든 장비들을 초기화하고 장비를 시작함'''
        pass

    def off_device(self):
        '''펌프를 끄고 장비를 정지함'''
        pass

    def get_temp_and_humidity(self)->list[float, float] :
        '''온도 및 습도 측정해 반환하는 함수'''
        pass

    def get_ec(self)->float :
        '''EC(전기전도도) 측정해 반환하는 함수'''
        pass
    def get_ph(self)->float :

    # MCP3008 모듈의 SPI 통신 설정
    spi = busio.SPI(clock=board.SCK, MISO=board.MISO, MOSI=board.MOSI)

    # MCP3008 모듈 초기화
    mcp = MCP.MCP3008(spi)

    # 아날로그 입력 채널 설정 (0번 핀을 사용하려면 CH0 사용)
    channel = AnalogIn(mcp, MCP.P0)

    # 여러 번 측정하여 평균값을 계산합니다.
    num_samples = 10
    total_ph = 0.0
    for _ in range(num_samples):
        # 아날로그 값을 읽어옵니다.
        raw_value = channel.value
        # ADC 값을 전압 값으로 변환합니다.
        voltage = raw_value / 65535.0 * 5.0
        # pH 값을 계산합니다. (변환식은 pH 측정 센서에 따라 다를 수 있습니다.)
        # 해당 변환식은 예시일 뿐, 실제 센서의 데이터시트를 참고해야 합니다.
        ph = 7 - (voltage - 2.5) * 3
        total_ph += ph
        # 측정 사이에 잠시 대기합니다.
        time.sleep(0.1)

    # 평균 pH 값을 계산합니다.
    avg_ph = total_ph / num_samples

    return avg_ph

# GPIO 모드 설정
GPIO.setmode(GPIO.BCM)

# pH 값을 측정합니다.
pH_value = get_ph()
print(f"측정된 pH 값: {pH_value}")

# GPIO 모드 초기화
GPIO.cleanup()
'''
        pass

    def set_pump_state(self, state:str) :
        '''펌프 작동 상태 설정하는 함수'''
        pass

    def get_pump_state(self)->str :
        '''펌프 작동 상태 반환하는 함수 ('on'/'off')'''
        pass
    def get_water_level(self)->float :
        '''3층 물통 수위 측정해 반환하는 함수'''
        pass
    def set_light_state(self, level:int, state:str) :
        '''1층 혹은 2층 LED 전원 상태를 지정하는 함수'''
        pass
    def get_light_state(self)->list[str] :
        '''1층과 2층 LED 전원 상태를 얻어오는 함수 ['on'/'off', 'on'/'off']'''
        pass
    def set_heater_state(self, state:str) :
        '''전체 히터의 상태를 지정하는 함수'''
        pass
    def get_heater_state(self)->str :
        '''히터의 상태를 반환하는 함수 ('on'/'off')'''
        pass
