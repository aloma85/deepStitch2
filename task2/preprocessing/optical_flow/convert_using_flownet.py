import git
import sys
repo = git.Repo("./", search_parent_directories=True)
homedir = repo.working_dir
sys.path.insert(1, f"{homedir}" + '/utils')
import settings
sys.path.append(settings.flownet_dir) #This should include the modules from https://github.com/ClementPinard/FlowNetPytorch so import models works
import models

import argparse
import torch
import torch.backends.cudnn as cudnn
import torch.nn.functional as F
from tqdm import tqdm

import torchvision.transforms as transforms
import flow_transforms
from imageio import imread, imwrite
import numpy as np
from util import flow2rgb

import cv2
import os
import glob
from PIL import Image


def mp4_load(fn):
    # Take an MP4 video and return a list of frames
    vidcap = cv2.VideoCapture(fn)
    success,image = vidcap.read()
    out = []
    while True:
        success,image = vidcap.read()
        if not success:
            break
        else:
            image = np.array(Image.fromarray(image).resize((960, 540)))
            out.append(image[:, :, [2,1,0]])

    return out

##############################################################
parser = argparse.ArgumentParser(description='Conversion')
parser.add_argument('--mp4_fn', default=settings.raw_directory,type=str, help='input path')
parser.add_argument('--gpu_id', default=1,type=int, help='which gpu')
parser.add_argument('--window', default=4,type=int, help='sliding window for smoothing frames')
parser.add_argument('--join', default=2,type=int, help='write optical flow side by side to original if 2')
args = parser.parse_args()

model_dir = settings.flownet_model
mp4_fn = args.mp4_fn
gpu_id = args.gpu_id
window = args.window
join = args.join
torch.cuda.set_device(gpu_id) 



if __name__ == '__main__':
    input_transform = transforms.Compose([
        flow_transforms.ArrayToTensor(),
        transforms.Normalize(mean=[0,0,0], std=[255,255,255]),
        transforms.Normalize(mean=[0.411,0.432,0.45], std=[1,1,1])
    ])

    # create model
    network_data = torch.load(model_dir, map_location='cpu')
    print("=> using pre-trained model '{}'".format(network_data['arch']))
    model = models.__dict__[network_data['arch']](network_data).cuda()
    model.eval()
    cudnn.benchmark = True

    # if 'div_flow' in network_data.keys():
    #     args.div_flow = network_data['div_flow']


    mp4_ims = mp4_load(mp4_fn)
    n_im = len(mp4_ims) # Number of images

    export_ims = []
    [nY, nX, nC] = mp4_ims[0].shape

    #frame_ints = list(range(n_im))
    div_flow = 2
    max_flow = 20
    outs = []

    for ii in tqdm(range(n_im-window)):
        
        aa=ii
        bb=ii+window

        img1 = input_transform(mp4_ims[aa])
        img2 = input_transform(mp4_ims[bb])
        input_var = torch.cat([img1, img2]).unsqueeze(0)

        # if args.bidirectional:
        # feed inverted pair along with normal pair
        inverted_input_var = torch.cat([img2, img1]).unsqueeze(0)
        input_var = torch.cat([input_var, inverted_input_var])

        input_var = input_var.cuda()
        # compute output
        output = model(input_var)

        outs.append(np.array(output.cpu().detach()))

        # Upsample
        output = F.interpolate(output, size=img1.size()[-2:], mode='bilinear', align_corners=False)

        # Convert to an RGBim1.
        for suffix, flow_output in zip(['flow', 'inv_flow'], output):
            rgb_flow = flow2rgb(div_flow * flow_output, max_value=max_flow)
            to_save = (rgb_flow * 255).astype(np.uint8).transpose(1,2,0)

        combined = np.zeros([nY, join*nX, nC], dtype=np.uint8)
        if join == 2:
            combined[:, :nX, :] = mp4_ims[aa][:, :, [2,1,0]] # Invert back for BGR
            combined[:, nX:, :] = to_save
        else:
            combined[:, :, :] = to_save

        export_ims.append(combined) # Save for list

    # Write out the MP4
    subdir_out = os.path.join('/'.join(mp4_fn.split('/')[:-1]), "optical_flow")
    if not os.path.exists(subdir_out):
        os.makedirs(subdir_out)

    fn_out = os.path.join(subdir_out, 'flownet_'+ mp4_fn.split('/')[-1])

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(fn_out,fourcc, 30.0, (int(join*nX),int(nY)))

    for frame in export_ims:
        out.write(frame)

    out.release()
