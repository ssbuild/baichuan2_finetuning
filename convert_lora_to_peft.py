# -*- coding: utf-8 -*-
# @Time:  20:50
# @Author: tk
# @File：convert_lora_to_peft
import gc
import os
import re

import torch
from deep_training.data_helper import ModelArguments
from transformers import HfArgumentParser, AutoConfig, GenerationConfig
from data_utils import train_info_args, NN_DataHelper, global_args, build_messages
from aigc_zoo.model_zoo.baichuan2.llm_model import MyTransformer,LoraModel,LoraArguments,PromptArguments,BaichuanConfig,BaichuanTokenizer



def convert_to_peft(output_dir = './peft_lora'):
    train_info_args['seed'] = None
    parser = HfArgumentParser((ModelArguments,))
    (model_args,) = parser.parse_dict(train_info_args, allow_extra_keys=True)

    dataHelper = NN_DataHelper(model_args,)
    tokenizer, _, _, _ = dataHelper.load_tokenizer_and_config(config_class_name=BaichuanConfig,
                                                              tokenizer_class_name=BaichuanTokenizer, )

    ckpt_dir = './best_ckpt/last'
    config = BaichuanConfig.from_pretrained(ckpt_dir)

    lora_args = LoraArguments.from_pretrained(ckpt_dir)

    # 非推理模式
    lora_args.inference_mode = False

    new_num_tokens = config.vocab_size
    if config.task_specific_params is not None and config.task_specific_params.get('vocab_size', None) is not None:
        config.vocab_size = config.task_specific_params['vocab_size']

    pl_model = MyTransformer(config=config, model_args=model_args, lora_args=lora_args,
                             torch_dtype=torch.float16,
                             new_num_tokens=new_num_tokens,#扩充词
                             # load_in_8bit=global_args["load_in_8bit"],
                             # # device_map="auto",
                             # device_map = {"":0} # 第一块卡
                             )
    # 加载lora权重
    pl_model.load_sft_weight(ckpt_dir, is_trainable=True)

    lora_model: LoraModel = pl_model.backbone  # noqa

    lora_model.save_pretrained(output_dir)


    del pl_model
    gc.collect()

    #权重修改
    weight_file = os.path.join(output_dir,'adapter_model.bin')
    m = torch.load(weight_file)
    m_new = {}
    for k,v in m.items():
        m_new[re.sub(r'model.model_','model',k)] = v
    torch.save(m_new,weight_file)
    return tokenizer,config,lora_args



def get_base_model():
    train_info_args['seed'] = None
    parser = HfArgumentParser((ModelArguments,))
    (model_args,) = parser.parse_dict(train_info_args, allow_extra_keys=True)

    dataHelper = NN_DataHelper(model_args,)
    tokenizer, _, _, _ = dataHelper.load_tokenizer_and_config(config_class_name=BaichuanConfig,
                                                              tokenizer_class_name=BaichuanTokenizer, )

    ckpt_dir = './best_ckpt/last'
    config = BaichuanConfig.from_pretrained(ckpt_dir)


    pl_model = MyTransformer(config=config, model_args=model_args, torch_dtype=torch.float16, )

    return pl_model.get_llm_model()

if __name__ == '__main__':
    peft_lora_weight = './peft_lora'
    tokenizer,config,lora_args = convert_to_peft(peft_lora_weight)

    from transformers import AutoModelForCausalLM
    from peft import get_peft_config, get_peft_model, LoraConfig, TaskType,PeftModel



    peft_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        inference_mode=True,
        r=lora_args.r,
        lora_alpha=lora_args.lora_alpha,
        lora_dropout=lora_args.lora_dropout,
        bias=lora_args.bias,
        modules_to_save=lora_args.modules_to_save,
        layers_to_transform=lora_args.layers_to_transform,
        layers_pattern=lora_args.layers_pattern,
        target_modules=lora_args.target_modules
    )

    #覆盖配置文件
    peft_config.save_pretrained(peft_lora_weight)
    # model = AutoModelForCausalLM.from_pretrained(model_name_or_path)
    # model = get_peft_model(model, peft_config)
    # model.print_trainable_parameters()

    model = get_base_model()
    # model = get_peft_model(model, peft_config)
    model = PeftModel.from_pretrained(model,peft_lora_weight)
    model.print_trainable_parameters()

    model.eval().half().cuda()

    text_list = ["写一个诗歌，关于冬天",
                 "晚上睡不着应该怎么办",
                 "从南京到上海的路线",
                 ]

    for input in text_list:
        messages = build_messages(input)
        generation_config = GenerationConfig(eos_token_id=config.eos_token_id,
                                             pad_token_id=config.eos_token_id,
                                             do_sample=True, top_k=5, top_p=0.85, temperature=0.3,
                                             repetition_penalty=1.1, )
        response = model.chat(tokenizer, messages=messages, generation_config=generation_config)
        print('input', input)
        print('output', response)