import {
  Settings,
  Code,
  MessagesSquare,
  WandSparkles,
  AudioLinesIcon,
  SquareSlashIcon,
  MonitorIcon,
  HomeIcon,
  PowerIcon,
  GlobeIcon,
  MessageSquareTextIcon,
} from "lucide-react";
import { invoke } from "@tauri-apps/api/core";
import { GithubIcon } from "@/components";

export const useMenuItems = () => {

  const menu: {
    icon: React.ElementType;
    label: string;
    href: string;
    count?: number;
  }[] = [
    {
      icon: HomeIcon,
      label: "Dashboard",
      href: "/dashboard",
    },
    {
      icon: MessagesSquare,
      label: "Chats",
      href: "/chats",
    },
    {
      icon: WandSparkles,
      label: "System prompts",
      href: "/system-prompts",
    },
    {
      icon: Settings,
      label: "App Settings",
      href: "/settings",
    },
    {
      icon: MessageSquareTextIcon,
      label: "Responses",
      href: "/responses",
    },
    {
      icon: MonitorIcon,
      label: "Screenshot",
      href: "/screenshot",
    },
    {
      icon: AudioLinesIcon,
      label: "Audio",
      href: "/audio",
    },
    {
      icon: SquareSlashIcon,
      label: "Cursor & Shortcuts",
      href: "/shortcuts",
    },

    {
      icon: Code,
      label: "Dev space",
      href: "/dev-space",
    },
  ];

  const footerItems: {
    icon: React.ElementType;
    label: string;
    href?: string;
    action?: () => Promise<void>;
  }[] = [
    {
      icon: PowerIcon,
      label: "Выйти из Stella Conference",
      action: async () => {
        await invoke("exit_app");
      },
    },
  ];

  // attribution: Stella Conference is a modified version of Pluely (GPL-3.0)
  const footerLinks: {
    title: string;
    icon: React.ElementType;
    link: string;
  }[] = [
    {
      title: "Исходный код Stella Conference (GPL-3.0)",
      icon: GithubIcon,
      link: "https://github.com/a1x10/project3",
    },
    {
      title: "Основано на Pluely (Srikanth Nani)",
      icon: GlobeIcon,
      link: "https://github.com/iamsrikanthnani/pluely",
    },
  ];

  return {
    menu,
    footerItems,
    footerLinks,
  };
};
