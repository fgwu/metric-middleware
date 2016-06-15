from threading import Thread
import socket
import time
import pika
import redis
import json
import os


class Singleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):  # @NoSelf
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class CrystalIntrospectionControl():
    __metaclass__ = Singleton
    
    def __init__(self, conf, log):
        self.logger = log
        self.conf = conf
        
        self.control_thread = ControlThread(self.conf, self.logger)
        self.control_thread.daemon = True
        self.control_thread.start()
        
        self.publish_thread = PublishThread(self.conf, self.logger)
        self.publish_thread.daemon = True
        
        self.threads_started = False

    def get_metrics(self):
        return self.control_thread.metric_list 
    
    def publish_stateful_metric(self,routing_key, key, value):
        self.publish_thread.publish_statefull(routing_key, key, value)
    
    def publish_stateless_metric(self,routing_key, key, value):
        self.publish_thread.publish_stateless(routing_key, key, value)
        
class PublishThread(Thread):
    
    def __init__(self, conf, logger):
        Thread.__init__(self)
        
        self.logger = logger
        self.monitoring_statefull_data = dict()
        self.monitoring_stateless_data = dict()
        
        self.interval = conf.get('publish_interval',1.01)
        self.ip = conf.get('bind_ip')+":"+conf.get('bind_port')
        self.exchange = conf.get('exchange', 'amq.topic')
        
        rabbit_host = conf.get('rabbit_host')
        rabbit_port = int(conf.get('rabbit_port'))
        rabbit_user = conf.get('rabbit_username')
        rabbit_pass = conf.get('rabbit_password')

        credentials = pika.PlainCredentials(rabbit_user,rabbit_pass)  
        self.parameters = pika.ConnectionParameters(host = rabbit_host,
                                                    port = rabbit_port,
                                                    credentials = credentials)
      
    def publish_statefull(self, routing_key, key, value):
        if not routing_key in self.monitoring_statefull_data:
            self.monitoring_statefull_data[routing_key] = dict()
            if not key in self.monitoring_statefull_data[routing_key]:
                self.monitoring_statefull_data[routing_key][key] = 0
                
        self.monitoring_statefull_data[routing_key][key] += value
            
    def publish_stateless(self, routing_key, key, value):
        if not routing_key in self.monitoring_stateless_data:
            self.monitoring_stateless_data[routing_key] = dict()
            if not key in self.monitoring_stateless_data[routing_key]:
                self.monitoring_stateless_data[routing_key][key] = 0
                
        self.monitoring_stateless_data[routing_key][key] += value
       
    def run(self):
        data = dict()
        while True:
            time.sleep(self.interval)
            rabbit = pika.BlockingConnection(self.parameters)
            channel = rabbit.channel()
            
            for routing_key in self.monitoring_stateless_data.keys():
                data[self.ip] = self.monitoring_stateless_data[routing_key].copy()
                
                for key in self.monitoring_stateless_data[routing_key].keys():
                    if self.monitoring_stateless_data[routing_key][key] == 0:
                        del self.monitoring_stateless_data[routing_key]
                    else:
                        self.monitoring_stateless_data[routing_key][key] = 0
                        
                channel.basic_publish(exchange=self.exchange, 
                                      routing_key=routing_key, 
                                      body=json.dumps(data))
                
            for routing_key in self.monitoring_statefull_data.keys():
                data[self.ip] = self.monitoring_statefull_data[routing_key].copy()
                        
                channel.basic_publish(exchange=self.exchange, 
                                      routing_key=routing_key, 
                                      body=json.dumps(data))
                
     
class ControlThread(Thread):
    
    def __init__(self, conf, logger):
        Thread.__init__(self)
        
        self.conf = conf
        self.logger = logger
        self.server = self.conf.get('execution_server')
        self.interval = self.conf.get('control_interval',10)
        redis_host = self.conf.get('redis_host')
        redis_port = self.conf.get('redis_port')
        redis_db = self.conf.get('redis_db')
        
        self.host_name = socket.gethostname()
        self.host_ip = socket.gethostbyname(self.host_name)   
        
        
        self.redis = redis.StrictRedis(redis_host,
                                       redis_port,
                                       redis_db)
        
        self.metric_list = {}
        
        
    def _get_swift_disk_usage(self):
        swift_devices = dict()
        for disk in os.listdir('/srv/node/'):
            statvfs = os.statvfs('/dev/'+disk)
            swift_devices[disk] = dict()
            swift_devices[disk]['size'] = statvfs.f_frsize * statvfs.f_blocks
            swift_devices[disk]['free'] = statvfs.f_frsize * statvfs.f_bfree
      
        return swift_devices
    
    def run(self):
        while True: 
            swift_usage = self._get_swift_disk_usage()
            self.metric_list = self.redis.hgetall("metrics")
            self.redis.hmset('node:'+self.host_name,{'type':self.server,'name':self.host_name,'ip':self.host_ip, 'last_ping':time.time(), 'devices':json.dumps(swift_usage)})
            time.sleep(self.interval)
