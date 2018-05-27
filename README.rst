# PPNetwork

PPNetwork 是无中心节点的虚拟局网。任何节点，无论位于Internet或者防火墙后，只需要安装该软件，运行后，就可以建立和其他节点之间的虚拟局域网。如办公室和家庭电脑直接组建虚拟局网，或者亲友之间建立虚拟局网，在局网上进行文件共享等。

## 简要原理

节点运行后，会尝试连接网络上其他节点，通过网络各节点寻找相同的VLAN号和Secret的节点，并启动虚拟网卡，虚拟局域网就可以使用了。

## 安装

### Linux

pip install python-ppnetwork

### windows 

1.  需要先安装openvpn中的tapdriver
2.  如果安装了python和pip , 可以直接
	pip install python-ppnetwork
    如果不想安装python，则可以下载 执行版
    pan.baidu.com
    
## 配置

配置文件采用yaml格式。文件名称自定义，如ppnetwork.yaml

示例如下：
{
#ppnet 
node_id: 818300194,
node_port: 54194,

node_nic: "无线网卡",
DebugLevel: 20,
#DebugFile: 'pplink.log',

node_file: nodes.pkl,
node_type: client,

#flow
flow:  {
          "flow_port": 9000,
          },

#service
"services": {
      "vpn": enable,
        },         
    
 #vpn
 vpn: {
       VlanId : 0,
       IPRange : { start : 192.168.33.1, end : 192.168.33.255 },
       VlanIP : 0.0.0.0,
       VlanMask : 255.255.255.0,
       VlanSecret : "12345678",
 }   
} 

## 运行

ppnetwork -h | --help   帮助
ppnetwork  --config  pp.yaml   用指定的配置文件（pp.yaml） 运行。
ppnetwork     用缺省配置文件ppnetwork.yaml 运行
 

#  安全说明
1.  任何节点加入虚拟局网接入都需要验证，网络号+密钥 +时间窗口。 
2.  所有虚拟网络中数据传输为透传，没有使用加密。
3.  虚拟网中的地址分配，可以自行指定，也可以动态获得（配置文件中为0.0.0.0）。
      如果自行指定有冲突，后进入者会动态分配另一个空闲地址。可以通过网络命令 如 ifconfig 或 ipconfig 查看
4.  网络号和网络地址段必须保持一致，否则会导致地址分配错误。

## 激励原则
1.   按转发流量、时段、区域（时延） 激励 

