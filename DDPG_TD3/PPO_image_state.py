import torch
import torch.nn as nn
from torch.distributions import MultivariateNormal
import gym
import numpy as np

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

feat_size = 4
latent_dim = feat_size**2 * 128

## Utilities
class Flatten(torch.nn.Module):
    def forward(self, x):
        return x.view(x.size(0), -1)

class Memory:
    def __init__(self):
        self.actions = []
        self.states = []
        self.logprobs = []
        self.rewards = []
        # self.obs = []

    def clear_memory(self):
        del self.actions[:]
        del self.states[:]
        del self.logprobs[:]
        del self.rewards[:]
        # del self.obs[:]

class ActorCritic(nn.Module):
	def __init__(self, img_stack, state_dim, action_dim, action_std):
		super(ActorCritic, self).__init__()
		# action mean range -1 to 1

		self.encoder = nn.Sequential(  ## input size:[224, 224]
			nn.Conv2d(img_stack, 16, 5, 4, padding=2),  ## output size: [16, 56, 56]
			nn.ReLU(),
			nn.BatchNorm2d(16),
			nn.Conv2d(16, 32, 5, 2, padding=2),  ## output size: [32, 28, 28]
			nn.ReLU(),
			nn.BatchNorm2d(32),
			nn.Conv2d(32, 64, 5, 2, padding=2),  ## output size: [64, 14, 14]
			nn.ReLU(),
			nn.BatchNorm2d(64),
			nn.Conv2d(64, 128, 5, 4, padding=2),  ## output size: [128, 4, 4]
			nn.ReLU(),
			nn.BatchNorm2d(128),
			Flatten(),  ## output: 2048
		)

		self.actor = nn.Sequential(
			nn.Linear(latent_dim + state_dim, 400),
			nn.Tanh(),
			nn.Linear(400, 300),
			nn.Tanh(),
			nn.Linear(300, action_dim),
			nn.Tanh()
		)
		# critic
		self.critic = nn.Sequential(
			nn.Linear(latent_dim + state_dim, 400),
			nn.Tanh(),
			nn.Linear(400, 300),
			nn.Tanh(),
			nn.Linear(300, 1)
		)
		self.action_var = torch.full((action_dim,), action_std * action_std).to(device)

	def forward(self):
		# for layer in self.cnn:
		# 	print(state.size())
		# 	state = layer(state)
		raise NotImplementedError

	def act(self, ob, state, memory):
		latent = self.encoder(ob)
		state = torch.cat((latent, state),1)
		action_mean = self.actor(state)
		dist = MultivariateNormal(action_mean, torch.diag(self.action_var).to(device))
		action = dist.sample()
		action_logprob = dist.log_prob(action)

		memory.states.append(state)
		# memory.obs.append(ob)
		memory.actions.append(action)
		memory.logprobs.append(action_logprob)

		return action.detach()

	def evaluate(self, state, action):
		# latent = self.encoder(ob)
		# state = torch.cat((latent, state),1)
		action_mean = self.actor(state)
		dist = MultivariateNormal(torch.squeeze(action_mean), torch.diag(self.action_var))

		action_logprobs = dist.log_prob(torch.squeeze(action))
		dist_entropy = dist.entropy()
		state_value = self.critic(state)

		return action_logprobs, torch.squeeze(state_value), dist_entropy


class PPO:
	def __init__(self, img_stack, state_dim, action_dim, action_std, lr, betas, gamma, K_epochs, eps_clip):
		self.lr = lr
		self.betas = betas
		self.gamma = gamma
		self.eps_clip = eps_clip
		self.K_epochs = K_epochs

		self.policy = ActorCritic(img_stack, state_dim, action_dim, action_std).to(device)
		self.optimizer = torch.optim.Adam(self.policy.parameters(),
		                                  lr=lr, betas=betas)
		self.policy_old = ActorCritic(img_stack, state_dim, action_dim, action_std).to(device)

		self.MseLoss = nn.MSELoss()

	def select_action(self, ob, state, memory):
		state = torch.FloatTensor(state.reshape(1, -1)).to(device)
		ob = torch.FloatTensor(ob).to(device)
		return self.policy_old.act(ob, state, memory).cpu().data.numpy().flatten()

	def update(self, memory):
		# Monte Carlo estimate of rewards:
		rewards = []
		discounted_reward = 0
		for reward in reversed(memory.rewards):
			discounted_reward = reward + (self.gamma * discounted_reward)
			rewards.insert(0, discounted_reward)

		# Normalizing the rewards:
		rewards = torch.tensor(rewards).to(device)
		if rewards.shape[0] == 1:
			rewards = (rewards - rewards.mean()) / (0 + 1e-5)
		else:
			rewards = (rewards - rewards.mean()) / (rewards.std() + 1e-5)

		# convert list to tensor
		old_states = torch.stack(memory.states).to(device).detach()
		old_actions = torch.stack(memory.actions).to(device).detach()
		old_logprobs = torch.squeeze(torch.stack(memory.logprobs)).to(device).detach()

		# Optimize policy for K epochs:
		for _ in range(self.K_epochs):
			# Evaluating old actions and values :
			logprobs, state_values, dist_entropy = self.policy.evaluate(old_states, old_actions)

			# Finding the ratio (pi_theta / pi_theta__old):
			ratios = torch.exp(logprobs - old_logprobs.detach())

			# Finding Surrogate Loss:
			advantages = rewards - state_values.detach()
			surr1 = ratios * advantages
			surr2 = torch.clamp(ratios, 1 - self.eps_clip, 1 + self.eps_clip) * advantages
			loss = -torch.min(surr1, surr2) + 0.5 * self.MseLoss(state_values, rewards) - 0.01 * dist_entropy

			# take gradient step
			self.optimizer.zero_grad()
			loss.mean().backward()
			self.optimizer.step()

		# Copy new weights into old policy:
		self.policy_old.load_state_dict(self.policy.state_dict())