import numpy as np
import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F
import utils

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


# Implementation of Twin Delayed Deep Deterministic Policy Gradients (TD3)
# Paper: https://arxiv.org/abs/1802.09477


class Actor(nn.Module):
    def __init__(self, state_dim, action_dim):
        super(Actor, self).__init__()

        # self.l1 = nn.Linear(state_dim, 400)
        # self.l2 = nn.Linear(400, 300)
        # self.l3 = nn.Linear(300,200)
        # self.l4 = nn.Linear(200,100)
        # self.l5 = nn.Linear(100, action_dim)


        self.l1 = nn.Linear(state_dim, 400)
        self.l2 = nn.Linear(400, 300)
        self.l3_linear = nn.Linear(300, int(action_dim/2))
        self.l3_angular = nn.Linear(300, int(action_dim/2))


    def forward(self, x):
        # x = F.relu(self.l1(x))
        # x = F.relu(self.l2(x))
        # x = F.relu(self.l3(x))
        # x = F.relu(self.l4(x))
        # x = self.max_action * torch.tanh(self.l5(x))

        x = F.relu(self.l1(x))
        x = F.relu(self.l2(x))

        out_linear = torch.sigmoid(self.l3_linear(x))
        out_angular = torch.tanh(self.l3_angular(x))
        x = torch.cat((out_linear,out_angular),1)

        # x = self.max_action * torch.tanh(self.l3(x))

        return x


class Critic(nn.Module):
    def __init__(self, state_dim, action_dim):
        super(Critic, self).__init__()

        # Q1 architecture
        # self.l1_1 = nn.Linear(state_dim + action_dim, 400)
        # self.l1_2 = nn.Linear(400, 300)
        # self.l1_3 = nn.Linear(300,200)
        # self.l1_4 = nn.Linear(200,100)
        # self.l1_5 = nn.Linear(100, 1)

        self.l1_1 = nn.Linear(state_dim + action_dim, 400)
        self.l1_2 = nn.Linear(400, 300)
        self.l1_3 = nn.Linear(300, 1)

        # Q2 architecture
        # self.l2_1 = nn.Linear(state_dim + action_dim, 400)
        # self.l2_2 = nn.Linear(400, 300)
        # self.l2_3 = nn.Linear(300,200)
        # self.l2_4 = nn.Linear(200,100)
        # self.l2_5 = nn.Linear(100, 1)

        self.l2_1 = nn.Linear(state_dim + action_dim, 400)
        self.l2_2 = nn.Linear(400, 300)
        self.l2_3 = nn.Linear(300, 1)

    def forward(self, x, u):
        xu = torch.cat([x, u], 1)

        # x1 = F.relu(self.l1_1(xu))
        # x1 = F.relu(self.l1_2(x1))
        # x1 = F.relu(self.l1_3(x1))
        # x1 = F.relu(self.l1_4(x1))
        # x1 = self.l1_5(x1)
        #
        # x2 = F.relu(self.l2_1(xu))
        # x2 = F.relu(self.l2_2(x2))
        # x2 = F.relu(self.l2_3(x2))
        # x2 = F.relu(self.l2_4(x2))
        # x2 = self.l2_5(x2)

        x1 = F.relu(self.l1_1(xu))
        x1 = F.relu(self.l1_2(x1))
        x1 = self.l1_3(x1)

        x2 = F.relu(self.l2_1(xu))
        x2 = F.relu(self.l2_2(x2))
        x2 = self.l2_3(x2)

        return x1, x2

    def Q1(self, x, u):
        xu = torch.cat([x, u], 1)

        # x1 = F.relu(self.l1_1(xu))
        # x1 = F.relu(self.l1_2(x1))
        # x1 = F.relu(self.l1_3(x1))
        # x1 = F.relu(self.l1_4(x1))
        # x1 = self.l1_5(x1)

        x1 = F.relu(self.l1_1(xu))
        x1 = F.relu(self.l1_2(x1))
        x1 = self.l1_3(x1)

        return x1


class TD3(object):
    def __init__(self, state_dim, action_dim):

        self.action_dim = action_dim

        self.actor = Actor(state_dim, action_dim).to(device)
        self.actor_target = Actor(state_dim, action_dim).to(device)
        self.actor_target.load_state_dict(self.actor.state_dict())
        self.actor_optimizer = torch.optim.Adam(self.actor.parameters())
        self.actor_loss = []

        self.critic = Critic(state_dim, action_dim).to(device)
        self.critic_target = Critic(state_dim, action_dim).to(device)
        self.critic_target.load_state_dict(self.critic.state_dict())
        self.critic_optimizer = torch.optim.Adam(self.critic.parameters())
        self.critic_loss = []


    def select_action(self, state):
        state = torch.FloatTensor(state.reshape(1, -1)).to(device)
        return self.actor(state).cpu().data.numpy().flatten()

    def train(self, replay_buffer, iterations, beta_PER, batch_size=100, discount=0.99, tau=0.005, policy_noise=0.2,
              noise_clip=0.5, policy_freq=2):

        for it in range(iterations):

            # Sample replay buffer
            x, y, u, r, d, indices, w = replay_buffer.sample(batch_size, beta = beta_PER)
            state = torch.FloatTensor(x).to(device)
            u = u.reshape((batch_size, self.action_dim))
            action = torch.FloatTensor(u).to(device)
            next_state = torch.FloatTensor(y).to(device)
            done = torch.FloatTensor(1 - d).to(device)
            reward = torch.FloatTensor(r).to(device)
            w = w.reshape((batch_size,-1))
            weights = torch.FloatTensor(w).to(device)

            # Select action according to policy and add clipped noise
            noise = torch.FloatTensor(u).data.normal_(0, policy_noise).to(device)
            noise = noise.clamp(-noise_clip, noise_clip)
            next_action = (self.actor_target(next_state) + noise)
            next_action[0] = torch.clamp(next_action[0],0,1)
            next_action[1] = torch.clamp(next_action[1], -1, 1 )

            # Compute the target Q value
            target_Q1, target_Q2 = self.critic_target(next_state, next_action)
            target_Q = torch.min(target_Q1, target_Q2)
            target_Q = reward + (done * discount * target_Q).detach()

            # Get current Q estimates
            current_Q1, current_Q2 = self.critic(state, action)

            # Compute critic loss
            critic_loss =  weights * ((current_Q1 - target_Q).pow(2) + (current_Q2 - target_Q).pow(2))
            # critic_loss = weights * (F.mse_loss(current_Q1, target_Q) + F.mse_loss(current_Q2, target_Q))
            prios = critic_loss + 1e-5
            critic_loss = critic_loss.mean()
            self.critic_loss.append(critic_loss)

            # Optimize the critic
            self.critic_optimizer.zero_grad()
            critic_loss.backward()
            replay_buffer.update_priorities(indices, prios.data.cpu().numpy())
            self.critic_optimizer.step()

            # Delayed policy updates
            if it % policy_freq == 0:

                # Compute actor loss
                actor_loss = -self.critic.Q1(state, self.actor(state)).mean()
                self.actor_loss.append(actor_loss)

                # Optimize the actor
                self.actor_optimizer.zero_grad()
                actor_loss.backward()
                self.actor_optimizer.step()

                # Update the frozen target models
                for param, target_param in zip(self.critic.parameters(), self.critic_target.parameters()):
                    target_param.data.copy_(tau * param.data + (1 - tau) * target_param.data)

                for param, target_param in zip(self.actor.parameters(), self.actor_target.parameters()):
                    target_param.data.copy_(tau * param.data + (1 - tau) * target_param.data)

    def save(self, filename, directory):
        torch.save(self.actor.state_dict(), '%s/%s_actor.pth' % (directory, filename))
        torch.save(self.critic.state_dict(), '%s/%s_critic.pth' % (directory, filename))

    def load(self, filename, directory):
        self.actor.load_state_dict(torch.load('%s/%s_actor.pth' % (directory, filename)))
        self.critic.load_state_dict(torch.load('%s/%s_critic.pth' % (directory, filename)))
