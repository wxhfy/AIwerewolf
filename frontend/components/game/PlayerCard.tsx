"use client";

import React from "react";
import { Player, Alignment } from "@/types";
import { useAppContext } from "@/context/AppContext";
import { t, tRole, format } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

interface PlayerCardProps {
  player: Player;
  isSelected?: boolean;
  onClick?: () => void;
}

export function PlayerCard({ player, isSelected, onClick }: PlayerCardProps) {
  const { viewMode, language } = useAppContext();

  const isWolf = player.alignment === Alignment.WOLF;
  const isVillage = player.alignment === Alignment.VILLAGE;

  return (
    <Card
      className={cn(
        "p-3 transition-all duration-200 cursor-pointer",
        !player.alive && "opacity-50 grayscale",
        isSelected && "ring-2 ring-primary ring-offset-2"
      )}
      onClick={onClick}
    >
      <div className="flex items-start justify-between">
        <Badge variant="default">{player.seat}</Badge>
        {!player.alive && (
          <Badge variant="danger">{t("dead", language)}</Badge>
        )}
      </div>

      <div className="mt-2 text-center">
        <div className="font-medium text-textPrimary">{player.name}</div>
        <div className="mt-1 text-sm">
          {viewMode === "moderator" && player.role ? (
            <>
              <div
                className={cn(
                  "font-medium",
                  isWolf ? "text-danger" : isVillage ? "text-success" : ""
                )}
              >
                {tRole(player.role, language)}
              </div>
              {player.alignment && (
                <div className="text-xs text-textSecondary">
                  {player.alignment === "village"
                    ? t("village", language)
                    : t("wolf", language)}
                </div>
              )}
            </>
          ) : (
            <div className="text-textSecondary">{t("hiddenRole", language)}</div>
          )}
        </div>
      </div>

      {player.alive && (
        <div className="mt-2 text-center">
          <Badge variant="success">{t("alive", language)}</Badge>
        </div>
      )}
    </Card>
  );
}
